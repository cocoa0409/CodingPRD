"""Server-controlled logical clock (PRD §2.9).

On startup the clock reads exactly 2026-05-01T00:00:00Z and never falls back to
wall-clock time. A PlatformAdmin may advance it via /_clock/set_current_utc.
"""
from datetime import datetime, timezone

# Startup default per PRD §2.9.
DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


clock = Clock()
