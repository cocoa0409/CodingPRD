"""Server-side logical clock.

All time-dependent behavior is measured against this clock, never wall-clock.
On startup it reads exactly 2026-04-01T00:00:00Z and stays there until moved.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
