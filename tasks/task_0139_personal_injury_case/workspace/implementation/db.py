"""In-memory data store and logical clock for the Personal Injury Case API.

The logical clock is advanced only by POST /_clock/advance (seconds), keeping
unit tests deterministic. now() returns a monotonically increasing instant so
created_at / updated_at ordering is preserved even within a single advance.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """Logical clock anchored at process start; advanced by /_clock/advance."""

    def __init__(self):
        self._logical = datetime.now(timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        """Return logical + a microsecond tick — ensures monotonicity across ops."""
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def logical_now(self) -> datetime:
        """Return the underlying logical instant — no tick added."""
        return self._logical

    def advance_seconds(self, seconds: float) -> None:
        """Advance the clock forward by `seconds` (must be >= 0)."""
        self._logical = self._logical + timedelta(seconds=float(seconds))
        self._tick = 0

    def set_to(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._logical = dt.astimezone(timezone.utc)
        self._tick = 0


class DataStore:
    """In-memory store for every entity in the SCAFFOLD."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Per-entity dictionaries: id -> dict
        self.clients: dict[str, dict] = {}
        self.cases: dict[str, dict] = {}
        self.medical_requests: dict[str, dict] = {}
        self.damages: dict[str, dict] = {}                # keyed by damages.id
        self.damages_by_case: dict[str, str] = {}         # case_id -> damages.id
        self.liens: dict[str, dict] = {}
        self.demand_letters: dict[str, dict] = {}
        self.settlement_offers: dict[str, dict] = {}
        self.fee_agreements: dict[str, dict] = {}         # keyed by id
        self.fee_agreement_by_case: dict[str, str] = {}   # case_id -> agreement.id
        self.court_events: dict[str, dict] = {}
        self.disbursements: dict[str, dict] = {}          # keyed by id
        self.disbursement_by_case: dict[str, str] = {}    # case_id -> disbursement.id

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used throughout the app.
store = DataStore()
