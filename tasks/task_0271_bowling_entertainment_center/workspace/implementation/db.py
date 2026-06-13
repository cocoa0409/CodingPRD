"""In-memory data store. Empty at boot — NEVER seeded or preloaded.

Every entity is a plain dict stored in a per-collection dict keyed by id.
The server also keeps a settable "current_utc" clock (PRD §3.9) used by all
time-sensitive computations (check-in window, no-show, cancellation notice,
hold-age expiry).
"""
import uuid
from datetime import datetime, timezone

from response import now_iso


class DB:
    def __init__(self):
        # Each collection is id -> entity dict.
        self.rate_cards = {}
        self.lanes = {}
        self.bays = {}
        self.customers = {}
        self.party_packages = {}
        self.food_items = {}
        self.rental_items = {}
        self.reservations = {}
        self.food_lines = {}
        self.rental_lines = {}
        self.leagues = {}
        self.league_nights = {}

        # Server clock. Defaults to real wall-clock UTC until a test sets it.
        self._current_utc = None

    # --- clock -------------------------------------------------------------
    def current_utc(self):
        if self._current_utc is not None:
            return self._current_utc
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._current_utc = dt

    def advance_clock(self, minutes):
        from datetime import timedelta
        self._current_utc = self.current_utc() + timedelta(minutes=minutes)
        return self._current_utc

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def new_id():
        return str(uuid.uuid4())


db = DB()


def new_common(full=True):
    """System-managed common fields (PRD §2.4).

    full=True  -> id, created_at, updated_at, version (most entities)
    full=False -> id, created_at only (FoodOrderLine)
    """
    ts = now_iso()
    if full:
        return {
            "id": DB.new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
    return {"id": DB.new_id(), "created_at": ts}


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD §2.4 / §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
