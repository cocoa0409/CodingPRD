"""Logical clock. Starts at 2026-01-01T00:00:00Z; never reads wall time."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = _DEFAULT

    def now(self):
        return self.current

    def now_date(self):
        """Current logical date (a datetime.date)."""
        return self.current.date()

    def current_year(self):
        return self.current.year

    def set(self, dt):
        self.current = dt

    def iso(self):
        # ISO 8601 UTC with 3 fractional digits, trailing Z
        return _format_iso(self.current)


def _format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = Clock()
