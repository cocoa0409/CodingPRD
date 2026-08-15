"""Logical clock. Boots at exactly 2026-08-01T00:00:00Z; never reads wall clock."""
from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)


clock = LogicalClock()
