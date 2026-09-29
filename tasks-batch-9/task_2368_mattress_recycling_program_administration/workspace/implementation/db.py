"""In-memory data store and the server-side logical clock.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded here.  Tests build every precondition through the
declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone


class Store(object):
    def __init__(self):
        self.state_programs = {}
        self.fee_rate_schedules = {}
        self.registrants = {}
        self.sales_remittances = {}
        self.exemption_claims = {}
        self.collection_sites = {}
        self.volume_reports = {}
        self.haulers = {}
        self.recyclers = {}
        self.pickup_orders = {}
        self.load_inspections = {}
        self.commodity_output_records = {}
        self.take_back_deliveries = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock (PRD §2.4): startup value is exactly 2026-08-01T00:00:00Z and
# the server never falls back to wall-clock time for domain comparisons.
# --------------------------------------------------------------------------
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.raw = CLOCK_DEFAULT_RAW
        self.dt = CLOCK_DEFAULT_DT

    def set(self, raw, dt):
        self.raw = raw
        self.dt = dt

    def now(self):
        return self.dt

    def stamp(self):
        """The string form written into logical-clock timestamp fields."""
        return self.raw


clock = Clock()
