"""In-memory data store + the server-controlled logical clock.

Storage strategy (PRD §2 + scaffold §1.1):
    * Each entity dict maps id → resource dict.
    * Cross-aggregate access (K-1 references TaxYear and Beneficiary) is
      satisfied by iterating the relevant dict and filtering — sufficient
      for benchmark-scale data.
    * A single re-entrant lock serialises mutations to satisfy the
      first-writer-wins concurrency rules in scaffold §1.2.1.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """The system's logical clock.

    PRD §2.10 — `/_clock/advance` jumps to a supplied target instant;
    every subsequent call to now() returns the advanced value (plus a
    tiny monotonic tick so created_at / updated_at remain strictly
    distinguishable). Without an advance, the clock is anchored at the
    process start instant.
    """

    def __init__(self):
        self._logical = datetime.now(timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        # Tick by one microsecond per call so successive calls give
        # strictly-increasing timestamps without skipping the calendar day.
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def advance_to(self, target: datetime) -> None:
        """Advance to a target instant. Never moves backwards."""
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        if target > self._logical:
            self._logical = target
            self._tick = 0


class DataStore:
    """In-memory database for all entities + the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Entity tables (id → dict).
        self.trusts: dict = {}
        self.trustees: dict = {}
        self.beneficiaries: dict = {}
        self.assets: dict = {}
        self.transactions: dict = {}
        self.distributions: dict = {}
        self.tax_years: dict = {}
        self.k1s: dict = {}

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used across the app.
store = DataStore()
