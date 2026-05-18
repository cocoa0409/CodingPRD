"""In-memory data store + logical clock."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """Logical clock for PRD §2.9.

    Anchored at a deterministic start that strictly advances with each
    `now()` call (microsecond ticks) so created_at/updated_at remain
    distinguishable. Explicit ``advance_to(target)`` jumps the clock
    forward to a supplied instant (used by ``POST /_clock/advance``)
    and never moves backwards.
    """

    def __init__(self):
        # Anchor at the wall-clock moment of process start. Tests will
        # supply absolute ISO 8601 deadlines and advance the clock
        # forward to drive expirations.
        self._logical = datetime.now(timezone.utc).replace(microsecond=0)
        self._tick = 0

    def now(self) -> datetime:
        # Use millisecond ticks so that the serialized PRD §2.7
        # 3-fractional-digit timestamp is always distinct between
        # successive operations (avoids ambiguous equality in tests).
        self._tick += 1
        return self._logical + timedelta(milliseconds=self._tick)

    def advance_to(self, target: datetime) -> datetime:
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        target = target.astimezone(timezone.utc)
        if target > self._logical:
            self._logical = target
            self._tick = 0
        return self.now()


class DataStore:
    """In-memory database for all MLS entities + the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Each map: id -> dict
        self.agents: dict = {}
        self.listings: dict = {}
        self.buyers: dict = {}
        self.lockboxes: dict = {}  # lockbox id -> row
        self.lockbox_by_listing: dict = {}  # listing_id -> lockbox_id (single active)
        self.showings: dict = {}
        self.offers: dict = {}
        self.counters: dict = {}
        self.contingencies: dict = {}
        self.commission_splits: dict = {}

        # Active license numbers (for uniqueness check on ACTIVE agents).
        self.active_license_numbers: set = set()
        # Lockbox serial numbers (unique across all lockboxes regardless of status).
        self.lockbox_serials: set = set()

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used throughout the app.
store = DataStore()
