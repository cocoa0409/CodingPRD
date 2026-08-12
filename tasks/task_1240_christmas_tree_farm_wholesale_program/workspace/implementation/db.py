"""In-memory data store and the server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD 2.4: at server startup the logical clock reads exactly
# 2026-05-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence == created_at ASC order
        self.seasons = {}
        self.blocks = {}
        self.crop_lots = {}
        self.stand_buckets = {}
        self.surveys = {}
        self.buyers = {}
        self.orders = {}
        self.allocations = {}
        self.crews = {}
        self.tickets = {}
        self.loads = {}
        self.consignments = {}
        self.tags = {}
        self.culls = {}
        self.replant_plans = {}


store = Store()


def now():
    """The current logical-clock instant (never wall-clock)."""
    return store.clock
