"""Logical clock. Server default is exactly 2026-05-01T00:00:00Z; the wall
clock is never consulted for business behavior or timestamps."""
from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)


CLOCK = LogicalClock()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(CLOCK.now())


def today_iso():
    return CLOCK.today().isoformat()
