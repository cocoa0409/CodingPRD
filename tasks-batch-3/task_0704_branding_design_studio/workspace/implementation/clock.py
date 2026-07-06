"""Server logical clock (PRD §2.11).

At startup the clock reads exactly 2026-03-01T00:00:00Z, and before any
clock-setting call it holds that default and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant


clock = LogicalClock()
