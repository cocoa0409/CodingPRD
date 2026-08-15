"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z and is advanced
only via POST /fleet-wash/_clock/set_current_utc.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion counter for stable ordering
        self.customers = {}
        self.sites = {}
        self.vehicles = {}
        self.vans = {}
        self.technicians = {}
        self.contracts = {}
        self.subscriptions = {}
        self.orders = {}
        self.routes = {}
        self.stops = {}
        self.reports = {}
        self.audits = {}
        self.claims = {}
        self.incidents = {}
        self.invoices = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
