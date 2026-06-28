"""Server-wide logical clock.

The service NEVER reads wall-clock time. At startup the clock reads exactly
2026-01-01T00:00:00Z and holds that default until set via
POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def reset(self):
        self._now = DEFAULT_NOW


clock = Clock()
