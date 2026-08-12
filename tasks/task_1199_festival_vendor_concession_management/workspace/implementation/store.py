"""Process-local in-memory store.

The store starts completely empty on every boot — no seeding, no files, no
SQLite, no caches. Every entity is constructed via the declared API surface.
"""
import itertools
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)  # global monotonic insertion order
        # Logical clock: exactly 2026-05-01T00:00:00Z at startup; never wall clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.festivals = {}
        self.vendors = {}
        self.applications = {}
        self.zones = {}
        self.booths = {}
        self.assignments = {}
        self.inspections = {}
        self.slots = {}
        self.reservations = {}
        self.transactions = {}
        self.settlements = {}
        self.fines = {}
        self.reviews = {}

    def next_seq(self):
        return next(self.seq)


db = Store()
