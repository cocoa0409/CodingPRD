"""In-memory data store. Starts empty on every boot; the logical clock starts
at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time."""

import threading
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.markets = {}
        self.stores = {}
        self.sites = {}
        self.models = {}
        self.listings = {}
        self.visits = {}
        self.forecasts = {}
        self.members = {}
        self.reviews = {}
        self.votes = {}
        self.lois = {}
        self.leases = {}
        self.crews = {}
        self.milestones = {}
        self.snapshots = {}
        self.seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
