"""Server-controlled logical clock.

PRD 2.4: All date/time arithmetic reads from a single server-controlled logical
clock, never the host wall-clock. On startup the clock reads exactly
2026-01-01T00:00:00Z and stays there until explicitly set; it never drifts toward
real time.
"""
from datetime import datetime, timezone

# Startup default — exactly 2026-01-01T00:00:00Z.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        """Current logical instant as a timezone-aware UTC datetime."""
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def today_iso(self):
        """Logical-clock date as YYYY-MM-DD."""
        return self._now.date().isoformat()

    def today_date(self):
        return self._now.date()


clock = Clock()
