"""Server-controlled logical clock.

At startup the clock is fixed at exactly 2026-04-01T00:00:00Z. Before any
clock-setting call every read of "now" returns precisely this default instant
and never the real wall-clock. POST /_clock/set_current_utc advances it.
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
