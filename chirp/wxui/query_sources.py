# Copyright 2022 Dan Smith <chirp@f.danplanet.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import queue
import tempfile
import threading
import urllib

import wx
import wx.adv

from chirp import radioreference
from chirp.drivers import generic_csv
from chirp.sources import base
from chirp.sources import dmrmarc
from chirp.sources import repeaterbook
from chirp.wxui import config
from chirp.wxui import fips

CONF = config.get()
LOG = logging.getLogger(__name__)
QueryThreadEvent, EVT_QUERY_THREAD = wx.lib.newevent.NewCommandEvent()


class QueryThread(threading.Thread, base.QueryStatus):
    END_SENTINEL = object()

    def __init__(self, *a, **k):
        self.query_dialog = a[0]
        self.radio = a[1]
        super(QueryThread, self).__init__(*a[2:], **k)
        self.status_queue = queue.Queue()

    def run(self):
        try:
            self.radio.do_fetch(self, self.query_dialog.get_params())
        except Exception as e:
            LOG.exception('Failed to execute query: %s' % e)
            self.send_fail('Failed: %s' % str(e))

    def send_status(self, status, percent):
        self.query_dialog.status(status, percent)

    def send_end(self):
        self.query_dialog.end()

    def send_fail(self, reason):
        self.query_dialog.fail(reason)


class QuerySourceDialog(wx.Dialog):
    NAME = 'NetworkSource'

    def __init__(self, *a, **k):
        super(QuerySourceDialog, self).__init__(*a, **k)
        vbox = self.build()
        self.Center()

        self.statusmsg = wx.StaticText(
            self, label='',
            style=(wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_NO_AUTORESIZE |
                   wx.ST_ELLIPSIZE_END))
        vbox.Add(self.statusmsg, proportion=0, border=5,
                 flag=wx.EXPAND | wx.BOTTOM)

        self.gauge = wx.Gauge(self)
        self.gauge.SetRange(100)
        vbox.Add(self.gauge, proportion=0, border=10,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT)

        link_label = urllib.parse.urlparse(self.get_link()).netloc
        link = wx.adv.HyperlinkCtrl(vbox.GetContainingWindow(),
                                    label=link_label, url=self.get_link(),
                                    style=wx.adv.HL_ALIGN_CENTRE)
        vbox.Insert(0, link, proportion=0, border=10,
                    flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM)
        info = wx.StaticText(vbox.GetContainingWindow(),
                             style=wx.ALIGN_CENTER_HORIZONTAL)
        info.SetLabelMarkup(self.get_info())
        vbox.Insert(0, info, proportion=0, border=10,
                 flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP)

        bs = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        vbox.Add(bs, border=10, flag=wx.LEFT | wx.ALIGN_CENTER_HORIZONTAL)
        self.Bind(wx.EVT_BUTTON, self._button)

        self.Bind(EVT_QUERY_THREAD, self._got_status)

        self.SetMinSize((400, 200))
        self.Fit()
        wx.CallAfter(self.Center)

        self.result_file = tempfile.NamedTemporaryFile(
            prefix='%s-' % self.NAME,
            suffix='.csv').name
        self.result_radio = None

    def _button(self, event):
        id = event.GetEventObject().GetId()

        if id == wx.ID_OK:
            self.FindWindowById(wx.ID_OK).Disable()
            self.do_query()
            return

        self.EndModal(id)

    def build(self):
        pass

    def do_query(self):
        LOG.info('Starting QueryThread for %s' % self.result_radio)
        QueryThread(self, self.result_radio).start()

    def get_params(self):
        pass

    def get_info(self):
        return ''

    def get_link(self):
        return ''

    def status(self, status, percent):
        wx.PostEvent(self, QueryThreadEvent(self.GetId(),
                                            status=status, percent=percent))

    def end(self):
        self.status(None, 100)

    def fail(self, reason):
        self.status(reason, 100)

    def _got_status(self, event):
        self.gauge.SetValue(event.percent)
        if event.status is None:
            self.EndModal(wx.ID_OK)
        else:
            self.statusmsg.SetLabel(event.status)
        if event.percent == 100:
            self.FindWindowById(wx.ID_OK).Enable()


class RRCALOGINQueryThread(QueryThread):
    global rrloggedin
    rrloggedin = False

    def do_query(self):
        global rrloggedin
        if rrloggedin:
            rrloggedin = False
            self.finalRRquery()
        else:
            self.do_loginRR()

    def do_loginRR(self):
        global clist, provinces, default_county, rrloggedin
        self.send_status('Logging In', 10)
# Do the SOAP queries
        provincecounty = radioreference.RadioReferenceRadio(None)
        provincecounty.set_params(**self.query_dialog.get_rrlogin_params())
        cancounties = provincecounty.do_getcanadacounties()
        clist = cancounties[0]
        provinces = cancounties[1]
# this should probably be a language translatable thing, not hardcoded?
        self.send_status('Successfully Logged in', 100)  # we hope...
        rrloggedin = True
        RRCAQueryDialog.populatepc(self)
        return True

    def finalRRquery(self):
        global rrcounties, rrloggedin
        # Write our new favorite place to the conf file.
        # et the 2 other parameters we need to pass
        province_id = provinces[provchoice.GetStringSelection()]
        # Iterate over the pairs. There must be a better way...
        # They are all unique within each province.
        for key, value in rrcounties.items():
            if value == countychoice.GetStringSelection():
                county_id = key
        # Send it
        CONF.set("province", str(province_id), "radioreference")
        CONF.set("county", str(county_id), "radioreference")
        # We've got to have more data
        username = CONF.get("Username", "radioreference")
        passwd = CONF.get("Password", "radioreference")
        self.send_status('Querying', 10)
        # send in the old radioreference methods for heavy lifting
        r = radioreference.RadioReferenceRadio(None)
        r.set_params(county_id, username, passwd, 'CA')
        r.do_fetch()
        f = r.get_features()  # wrote Dan an email about this
        if f.memory_bounds[1] == 0:
            self.send_fail('No results!')
            return
        self.send_status('Parsing', 50)

        csv = generic_csv.CSVRadio(None)
        for i in range(0, f.memory_bounds[1] + 1):
            m = r.get_memory(i)
            csv.set_memory(m)

        csv.save(self.query_dialog.result_file)

        self.send_end()


class RepeaterBookQueryDialog(QuerySourceDialog):
    NAME = 'Repeaterbook'
    RB_BANDS = {
        _('--All--'):                  0,
        _('10 meters (29MHz)'):        29,
        _('6 meters (54MHz)'):         5,
        _('2 meters (144MHz)'):        14,
        _('1.25 meters (220MHz)'):     22,
        _('70 centimeters (440MHz)'):  4,
        _('33 centimeters (900MHz)'):  9,
        _('23 centimeters (1.2GHz)'):  12,
    }

    def get_info(self):
        return (
            "RepeaterBook is Amateur Radio's most comprehensive,\n"
            "worldwide, FREE repeater directory.")

    def get_link(self):
        return 'https://repeaterbook.com'

    def build(self):
        self.tabs = wx.Notebook(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        vbox.Add(self.tabs, proportion=1, border=10,
                 flag=wx.EXPAND | wx.BOTTOM)

        self.tabs.InsertPage(0, self._build_political(self.tabs),
                             _('Political'))
        self.tabs.InsertPage(1, self._build_proximity(self.tabs),
                             _('Proximity'))
        self.Layout()
        return vbox

    def _build_band_choice(self, parent):
        return wx.Choice(parent, choices=list(self.RB_BANDS.keys()))

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def _build_political(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)

        self._state = wx.Choice(panel, choices=sorted(fips.FIPS_STATES.keys()))
        self.Bind(wx.EVT_CHOICE, self._selected_state, self._state)
        self._county = wx.Choice(panel, choices=['--All--'])
        self.Bind(wx.EVT_CHOICE, self._selected_county, self._county)
        self._pol_band = self._build_band_choice(panel)
        self.Bind(wx.EVT_CHOICE, self._selected_band, self._pol_band)

        self._fips_to_state = {str(v): k for k, v in fips.FIPS_STATES.items()}

        current_state = CONF.get('state', 'repeaterbook')
        current_county = CONF.get('county', 'repeaterbook')
        if not current_state:
            current_state = '1'
        self._state.SetSelection(
            self._state.FindString(self._fips_to_state[current_state]))
        self._selected_state_name(self._fips_to_state[current_state])

        try:
            _fips_to_county = {
                str(v): k
                for k, v in fips.FIPS_COUNTIES[int(current_state)].items()}
            self._county.SetSelection(
                self._county.FindString(_fips_to_county[current_county]))
        except Exception:
            if current_county:
                LOG.warning('Missing county code %r in state %r' % (
                    current_county,
                    current_state))

        self._add_grid(grid, _('State'), self._state)
        self._add_grid(grid, _('County'), self._county)
        self._add_grid(grid, _('Band'), self._pol_band)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, proportion=0, flag=wx.EXPAND | wx.TOP | wx.BOTTOM,
                 border=20)
        panel.SetSizer(vbox)
        return panel

    def _selected_state(self, event):
        self._selected_state_name(event.GetString())

    def _selected_state_name(self, state):
        counties = sorted(fips.FIPS_COUNTIES[fips.FIPS_STATES[state]].keys())
        self._county.Set(counties)
        CONF.set('state', str(fips.FIPS_STATES[state]), 'repeaterbook')
        self._selected_county_name(counties[0])

    def _selected_county(self, event):
        self._selected_county_name(event.GetString())

    def _selected_county_name(self, county):
        state = CONF.get('state', 'repeaterbook')
        try:
            state = int(state)
        except ValueError:
            pass
        county_code = str(fips.FIPS_COUNTIES[state][county])
        if county_code == '%':
            CONF.remove_option('county', 'repeaterbook')
        else:
            CONF.set('county', county_code, 'repeaterbook')

    def _build_proximity(self, parent):
        panel = wx.Panel(parent)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)

        self._location = wx.TextCtrl(panel)
        self._location.AppendText(CONF.get('location', 'repeaterbook') or '')
        self.Bind(wx.EVT_TEXT, self._selected_location, self._location)
        self._distance = wx.TextCtrl(panel)
        self._distance.AppendText(CONF.get('distance', 'repeaterbook') or '')
        self.Bind(wx.EVT_TEXT, self._selected_distance, self._distance)
        self._prox_band = self._build_band_choice(panel)
        self.Bind(wx.EVT_CHOICE, self._selected_band, self._prox_band)

        self._add_grid(grid, _('Location'), self._location)
        self._add_grid(grid, _('Distance'), self._distance)
        self._add_grid(grid, _('Band'), self._prox_band)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(grid, flag=wx.EXPAND | wx.TOP | wx.BOTTOM,
                 border=20)
        panel.SetSizer(vbox)
        return panel

    def _selected_location(self, event):
        CONF.set('location', event.GetString(), 'repeaterbook')

    def _selected_distance(self, event):
        CONF.set('distance', event.GetString(), 'repeaterbook')

    def _selected_band(self, event):
        CONF.set('band', str(self.RB_BANDS[event.GetString()]), 'repeaterbook')

    def do_query(self):
        self.result_radio = repeaterbook.RepeaterBook()
        super().do_query()

    def get_params(self):
        page = self.tabs.GetSelection()
        if page == 0:
            # Political
            return {
                '_url': 'query/rb/1.0/chirp',
                'state_id': CONF.get('state', 'repeaterbook'),
                'county_id': CONF.get('county', 'repeaterbook') or '%',
                'func': 'default',
                'band': CONF.get('band', 'repeaterbook') or '%',
                'freq': '%',
                'band6': '%',
                'loc': '%',
                'status_id': '%',
                'features': '%',
                'coverage': '%',
                'use': '%',
            }
        elif page == 1:
            # Proximity
            try:
                return {
                    '_url': 'query/rb/1.0/app_direct',
                    'loc': CONF.get('location', 'repeaterbook'),
                    'dist': int(CONF.get('distance', 'repeaterbook')),
                    'band': CONF.get('band', 'repeaterbook') or '%',
                }
            except (TypeError, ValueError):
                raise Exception(_('Distance must be a number!'))


class DMRMARCQueryDialog(QuerySourceDialog):
    NAME = 'DMR-MARC'

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, 1, flag=wx.EXPAND | wx.ALL, border=20)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        self._city = wx.TextCtrl(panel,
                                 value=CONF.get('city', 'dmrmarc') or '')
        self._add_grid(grid, _('City'), self._city)
        self._state = wx.TextCtrl(panel,
                                  value=CONF.get('state', 'dmrmarc') or '')
        self._add_grid(grid, _('State'), self._state)
        self._country = wx.TextCtrl(panel,
                                    value=CONF.get('country', 'dmrmarc') or '')
        self._add_grid(grid, _('Country'), self._country)

        return vbox

    def get_info(self):
        return 'The DMR-MARC Worldwide Network'

    def get_link(self):
        return 'https://www.dmr-marc.net'

    def do_query(self):
        CONF.set('city', self._city.GetValue(), 'dmrmarc')
        CONF.set('state', self._state.GetValue(), 'dmrmarc')
        CONF.set('country', self._country.GetValue(), 'dmrmarc')
        self.result_radio = dmrmarc.DMRMARCRadio()
        super().do_query()

    def get_params(self):
        return {'city': CONF.get('city', 'dmrmarc'),
                'state': CONF.get('state', 'dmrmarc'),
                'country': CONF.get('country', 'dmrmarc')}


class RRCAQueryDialog(QuerySourceDialog):
    NAME = 'RadioReferenceCanada'

    def get_info(self):
        return (
            "RadioReference.com is the world's largest\n"
            "radio communications data provider\n"
            "<small>Premium account required</small>")

    def get_link(self):
        return 'https://www.radioreference.com/apps/content/?cid=3'

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        global rrloggedin
        rrloggedin = False
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, 1, flag=wx.EXPAND | wx.ALL, border=20)
        grid = wx.FlexGridSizer(3, 5, 0)
        grid.AddGrowableCol(1)
# build the login elements
        global provchoice, countychoice, rrusername, rrpassword, loginbutton
        rrusername = wx.TextCtrl(panel,
                                 value=CONF.get('Username',
                                                'radioreference') or '')
        self._add_grid(grid, 'Username', rrusername)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        rrpassword = wx.TextCtrl(panel, style=wx.TE_PASSWORD,
                                 value=CONF.get('Password',
                                                'radioreference') or '')
        self._add_grid(grid, 'Password', rrpassword)
# build a new login button
        loginbutton = wx.Button(panel, id=wx.ID_OK, label='Log In')
        grid.Add(loginbutton)
        self.Bind(wx.EVT_BUTTON, self._button)
# build a prov/county selector grid & add selectors
        provchoice = wx.Choice(panel, choices=["Log in First"])
        provchoice.SetSelection(0)
        self.Bind(wx.EVT_CHOICE, self.populateprov, provchoice)
        self._add_grid(grid, 'Province', provchoice)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        countychoice = wx.Choice(panel, choices=["Select Province First"])
        wx.Choice.SetSelection(countychoice, 0)
        self._add_grid(grid, 'County', countychoice)
        grid.Add(wx.StaticText(panel, label=''),
                 border=20, flag=wx.ALIGN_CENTER | wx.RIGHT | wx.LEFT)
        panel.SetSizer(grid)
        vbox.Fit(self)

        return vbox

    def populateprov(self, event):
        self.selected_province(provchoice.GetStringSelection())

    def populatepc(self):
        # init and grab conf defaults and populate the selector
        RRCAQueryDialog.getconfdefaults(self)
        # Clear the temporary choice dropdown, disable the form bits we don't
        # need any more & insert provinces as exist in RR database because
        # they change sometimes.
        wx.CallAfter(provchoice.Clear)
        engprovs = []
        for key in provinces:
            engprovs.append(key)
        # It's a sort of time machine
        wx.CallAfter(provchoice.Append, engprovs)
        wx.CallAfter(rrusername.Enable, False)
        wx.CallAfter(rrpassword.Enable, False)
        wx.CallAfter(loginbutton.Enable, False)
        if self.default_prov:
            wx.CallAfter(provchoice.SetStringSelection, self.default_prov)
            # update the choice to match conf
            RRCAQueryDialog.selected_province(self, self.default_prov)
        if self.default_county:
            wx.CallAfter(countychoice.SetStringSelection, self.default_county)

    def getconfdefaults(self):
        code = CONF.get("province", "radioreference")
        for k, v in provinces.items():
            if code == str(v):
                self.default_prov = k
                break
            else:
                self.default_prov = "BC"
        code = CONF.get("county", "radioreference")
        for row in clist:
            if code == str(row[2]):
                self.default_county = row[3]
                break
            else:
                self.default_county = 0

    def selected_province(self, chosenprov):
        # if user alters the province dropdown, load the new counties into
        # the county dropdown choice
        global rrcounties
        rrcounties = {}
        self.chosenprov = provchoice.GetSelection()
        countychoice.Clear()
        for x in clist:
            if x[1] == chosenprov:
                countychoice.Append(x[3])
                rrcounties[x[2]] = x[3]

    def do_query(self):
        CONF.set('username', rrusername.GetValue(), 'radioreference')
        CONF.set('password', rrpassword.GetValue(), 'radioreference')
        RRCALOGINQueryThread(self).start()

    def get_rrlogin_params(self):
        return {'zipcounty': '',
                'username': CONF.get('Username', 'radioreference'),
                'password': CONF.get('Password', 'radioreference'),
                'country': ''}


class RRUSQueryDialog(QuerySourceDialog):  # NOT IMPLEMENTED YET
    NAME = 'RadioReferenceUSA'

    def _add_grid(self, grid, label, widget):
        grid.Add(wx.StaticText(widget.GetParent(), label=label),
                 border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)
        grid.Add(widget, 1, border=20, flag=wx.EXPAND | wx.RIGHT | wx.LEFT)

    def build(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(vbox)
        panel = wx.Panel(self)
        vbox.Add(panel, 1, flag=wx.EXPAND | wx.ALL, border=20)
        grid = wx.FlexGridSizer(2, 5, 0)
        grid.AddGrowableCol(1)
        panel.SetSizer(grid)

        self._city = wx.TextCtrl(panel,
                                 value=CONF.get('city', 'dmrmarc') or '')
        self._add_grid(grid, 'City', self._city)
        self._state = wx.TextCtrl(panel,
                                  value=CONF.get('state', 'dmrmarc') or '')
        self._add_grid(grid, 'State', self._state)
        self._country = wx.TextCtrl(panel,
                                    value=CONF.get('country', 'dmrmarc') or '')
        self._add_grid(grid, 'Country', self._country)

        return vbox

    def do_query(self):
        CONF.set('city', self._city.GetValue(), 'dmrmarc')
        CONF.set('state', self._state.GetValue(), 'dmrmarc')
        CONF.set('country', self._country.GetValue(), 'dmrmarc')
        #DMRMARCQueryThread(self).start()

    def get_dm_params(self):
        return {'city': CONF.get('city', 'dmrmarc'),
                'state': CONF.get('state', 'dmrmarc'),
                'country': CONF.get('country', 'dmrmarc')}
