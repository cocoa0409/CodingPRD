"""In-memory data store and logical clock.

Storage is process-local Python dicts keyed by id. No disk, no SQLite.
The store starts EMPTY on every boot -- nothing is seeded at startup.
"""
import threading
from datetime import datetime, timezone


DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic creation counter for stable ordering
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.pricing_configs = {}
        self.zones = {}
        self.customers = {}
        self.routes = {}
        self.stops = {}
        self.ledger = {}
        self.rentals = {}
        self.addons = {}
        self.invoices = {}
        self.payments = {}
        self.work_orders = {}
        self.skip_credits = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()
