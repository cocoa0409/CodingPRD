"""Server-side logical clock. Boots at 2026-05-01T00:00:00Z; every date/time
decision reads this clock, never the real wall clock."""
from datetime import datetime, timezone


def format_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)

    def iso(self):
        return format_ts(self._now)

    def today(self):
        """Current logical calendar date (YYYY-MM-DD string)."""
        return self._now.date().isoformat()

    def today_date(self):
        return self._now.date()


clock = LogicalClock()
