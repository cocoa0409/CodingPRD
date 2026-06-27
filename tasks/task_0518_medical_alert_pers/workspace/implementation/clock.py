"""Server-controlled logical clock.

PRD 2.8: Every time-dependent rule reads a server-controlled logical clock rather
than wall-clock time. At startup the clock reads exactly 2026-05-01T00:00:00Z, and
before any clock-set call it holds this default and never falls back to real time.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        # dt is a timezone-aware datetime
        self._now = dt


clock = Clock()
