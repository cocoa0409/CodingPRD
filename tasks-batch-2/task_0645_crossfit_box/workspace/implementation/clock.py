"""Server-controlled logical clock (PRD §2.7).

All time-based rules evaluate against this clock rather than wall-clock time.
The clock defaults to 2026-01-01T00:00:00Z at startup and never falls back to
wall-clock time before it has been explicitly set.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        # PRD §2.7: defaults to 2026-01-01T00:00:00Z at startup.
        self._now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


clock = Clock()
