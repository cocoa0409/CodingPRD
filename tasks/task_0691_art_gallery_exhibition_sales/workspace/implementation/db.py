"""In-memory data store. NO seeding — every collection starts empty on boot.

State is wiped on every process restart (per-test-server isolation). All entity
data is created by tests via the API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

import clock as clockmod


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock, shared across all galleries (PRD §2.7).
        self.clock_utc = clockmod.parse_iso(clockmod.DEFAULT_CLOCK)

        self.galleries = {}
        self.artists = {}
        self.artworks = {}
        self.exhibitions = {}
        self.wall_slots = {}
        self.sales = {}
        self.payment_plans = {}
        self.leases = {}
        self.opening_events = {}
        self.rsvps = {}
        self.loans = {}
        self.payouts = {}

        # Monotonic counter to break created_at ties deterministically
        # (ascending insertion order) regardless of timestamp resolution.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())

    def now_dt(self):
        # Real wall-clock used ONLY for created_at/updated_at record stamps,
        # never for business logic (which uses self.clock_utc).
        return datetime.now(timezone.utc)


DB = Store()


def reset():
    """Reset all state (used only for clean reinitialization)."""
    global DB
    DB = Store()
