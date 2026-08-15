"""In-memory data store and server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD section 2.4: before any client call the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence for created_at ordering
        self.projects = {}
        self.trade_packages = {}
        self.punch_walks = {}
        self.punch_items = {}
        self.closeout_documents = {}
        self.training_sessions = {}
        self.retainage_releases = {}
        self.warranty_cases = {}


store = Store()

COLLECTIONS = [
    "projects", "trade_packages", "punch_walks", "punch_items",
    "closeout_documents", "training_sessions", "retainage_releases",
    "warranty_cases",
]
