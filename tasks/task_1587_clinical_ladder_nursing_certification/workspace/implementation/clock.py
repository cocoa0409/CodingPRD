"""Logical clock. Defaults to exactly 2026-08-01T00:00:00Z at server start
and never falls back to wall-clock time."""

from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def fiscal_year_of(dt):
    """July-anchored fiscal year label: year+1 when month >= 7 else year."""
    return dt.year + 1 if dt.month >= 7 else dt.year
