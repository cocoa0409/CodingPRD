"""In-memory data store.

Storage is process-local Python dicts keyed by entity id. Every boot starts
empty: NO entity is seeded, preloaded, or hardcoded at import time. Each
start.sh re-invocation is a fresh process and therefore a clean store.
"""
import threading
import uuid
from datetime import datetime, timezone


class Clock:
    """Server clock. Pinnable via POST /_clock/set_current_utc for deterministic
    completion timestamps / warranty expiry (PRD §3.12)."""

    def __init__(self):
        self._pinned = None  # datetime (tz-aware UTC) or None

    def set(self, dt):
        self._pinned = dt

    def now(self):
        if self._pinned is not None:
            return self._pinned
        return datetime.now(timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # One dict per collection, keyed by id.
        self.paint_products = {}
        self.crew_members = {}
        self.equipment = {}
        self.weather_windows = {}
        self.projects = {}
        self.surfaces = {}
        self.color_selections = {}
        self.line_items = {}
        self.change_orders = {}
        self.crew_assignments = {}
        self.payments = {}
        self.walkthroughs = {}
        self.warranty_claims = {}
        # Monotonic sequence to give every entity a stable creation order even
        # when several are minted within the same pinned-clock instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


# Module-level singleton store. Created empty; never seeded.
store = Store()
