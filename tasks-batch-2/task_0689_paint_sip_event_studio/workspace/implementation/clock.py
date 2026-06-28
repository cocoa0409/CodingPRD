"""Server-controlled logical clock.

All time-gated rules evaluate against this clock, never wall-clock time.
Startup default is 2026-04-01T00:00:00Z; before any /_clock/set_current_utc
call the clock reads exactly this default.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
