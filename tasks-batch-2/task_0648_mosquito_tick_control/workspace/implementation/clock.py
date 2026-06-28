"""Server-controlled logical clock (PRD §2.4).

All time-based rules (season roll-over, guarantee windows, date comparisons)
evaluate against this logical clock rather than wall-clock time. At server
startup the logical current instant is exactly 2026-04-01T00:00:00Z; before any
clock is explicitly set, reads return precisely this default and the server
never falls back to the real wall-clock.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        # PRD §2.4: defaults to 2026-04-01T00:00:00Z at startup.
        self._now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def today(self):
        """The logical current calendar date (YYYY-MM-DD), as a date object."""
        return self._now.date()

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


clock = Clock()
