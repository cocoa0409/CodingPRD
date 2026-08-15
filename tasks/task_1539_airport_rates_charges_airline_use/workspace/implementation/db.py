"""In-memory data store. Starts empty on every boot; the logical clock starts
at exactly 2026-08-01T00:00:00Z. No seeding, no persistence."""
import itertools

from util import DEFAULT_CLOCK_ISO, parse_iso


class Store:
    def __init__(self):
        self.fiscal_years = {}
        self.airlines = {}
        self.airlines_by_iata = {}
        self.agreements = {}
        self.rates_settings = {}
        self.comments = {}
        self.activity_records = {}
        self.capital_projects = {}
        self.mii_votes = {}
        self.settlements = {}
        self.settlement_lines = {}
        self.pfc_applications = {}
        # stable insertion-order counter for created_at tie-breaking in sorts
        self.seq = itertools.count(1)
        # logical clock: verbatim string (for echo) + parsed datetime
        self.clock_iso = DEFAULT_CLOCK_ISO
        self.clock_dt = parse_iso(DEFAULT_CLOCK_ISO)

    # -- logical clock ------------------------------------------------------
    def set_clock(self, iso_string, dt):
        self.clock_iso = iso_string
        self.clock_dt = dt


store = Store()
