"""Logical clock (PRD §2.8)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._lock = threading.RLock()
        # PRD §2.8 does not specify an initial value for the logical clock.
        # Start it at the real wall-clock time at process startup so that
        # tests using current-era birthdates derive expected life_stages.
        self._now = datetime.now(timezone.utc).replace(microsecond=0)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, dt: datetime) -> None:
        with self._lock:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            self._now = dt


logical_clock = LogicalClock()
