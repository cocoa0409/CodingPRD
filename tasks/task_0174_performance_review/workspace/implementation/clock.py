"""Logical clock used for any check that compares the current time to a
stored timestamp (PRD §2.13). Implementation is monotonic-forward."""

import threading
from datetime import datetime, timezone


class LogicalClock:
    """Advances forward only. The first read after start defaults to wall-clock now."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._now: datetime = datetime.now(timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            wall = datetime.now(timezone.utc)
            # Logical clock is at least wall-clock; advances pin it forward
            # so any explicit advance survives across requests.
            if wall > self._now:
                self._now = wall
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        """Move the clock to `target`. Earlier values are rejected (caller validates)."""
        with self._lock:
            if target < self._now:
                raise ValueError("clock can only move forward")
            self._now = target
            return self._now


clock = LogicalClock()
