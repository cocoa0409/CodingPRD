"""Server-side logical clock.

On startup the clock reads exactly 2026-04-01T00:00:00Z; until it is explicitly
set it remains at that default and never falls back to wall-clock time.
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
