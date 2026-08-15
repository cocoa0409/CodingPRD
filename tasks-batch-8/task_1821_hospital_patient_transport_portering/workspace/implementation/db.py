"""In-memory data store and the logical clock.

The store starts empty on every boot. No seeding is performed anywhere.
The logical clock starts at exactly 2026-08-01T00:00:00Z and is only ever
moved by POST /_clock/set_current_utc; it never falls back to wall-clock time.
"""

from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.locations = {}
        self.travel_edges = {}
        self.transporters = {}
        self.equipment_assets = {}
        self.requests = {}
        self.offers = {}
        self.cleaning_tasks = {}
        self.shifts = {}
        self.demand_curves = {}
        self.delay_records = {}
        self.seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    """Current logical instant."""
    return store.clock
