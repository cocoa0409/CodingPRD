"""In-memory data store and logical clock.

The clock is a logical clock advanced via POST /_clock/advance. now() returns
a strictly monotonic instant: the underlying logical wall is combined with
a microsecond tick so that timestamps within a single advance window remain
distinguishable and orderable.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _LogicalClock:
    """Anchored at process start; advanced only by POST /_clock/advance."""

    def __init__(self):
        self._logical = datetime.now(timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        """Strictly monotonic instant for created_at / updated_at stamping."""
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def logical_now(self) -> datetime:
        """The current logical wall-time, without the microsecond tick."""
        return self._logical

    def set_to(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        new_value = dt.astimezone(timezone.utc)
        # Clock never moves backward.
        if new_value < self._logical:
            return
        self._logical = new_value
        self._tick = 0


class DataStore:
    """Thread-safe in-memory store keyed by uuid."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _LogicalClock()

        # All entity tables. Each entity row is a plain dict.
        self.estates: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}
        self.beneficiaries: dict[str, dict] = {}
        self.designations: dict[str, dict] = {}
        self.fiduciaries: dict[str, dict] = {}
        self.guardianships: dict[str, dict] = {}
        self.hipaa_auths: dict[str, dict] = {}
        self.poas: dict[str, dict] = {}
        self.directives: dict[str, dict] = {}
        self.filings: dict[str, dict] = {}
        self.distributions: dict[str, dict] = {}

    def now(self) -> datetime:
        return self.clock.now()

    def logical_now(self) -> datetime:
        return self.clock.logical_now()


# Singleton.
store = DataStore()
