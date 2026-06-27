"""Logical clock (PRD §2.8).

At startup the logical clock reads exactly 2026-01-01T00:00:00Z and remains
there until an administrator explicitly sets it; it never falls back to the
host's real time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
