"""In-memory data store and the plant logical clock (PRD §2.4, §2.5).

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; nothing is seeded. A monotonic sequence number provides stable
insertion ordering (created_at ties resolve to insertion order).
"""
import itertools
import threading
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        self.clock = CLOCK_DEFAULT
        self.plants = {}
        self.tanks = {}
        self.readings = {}
        self.cylinders = {}
        self.fill_lots = {}
        self.analyses = {}
        self.customers = {}
        self.rentals = {}
        self.drivers = {}
        self.routes = {}
        self.installations = {}
        self.repl_orders = {}
        self.blends = {}
        self.billing_runs = {}

    def next_seq(self):
        return next(self.seq)


store = Store()
