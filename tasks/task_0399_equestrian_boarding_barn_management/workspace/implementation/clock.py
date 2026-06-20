"""Logical clock and ISO-8601 UTC (3 fractional digits) helpers.

PRD §2.11 / §3.10: temporal preconditions consult a logical clock whose value is
whatever was last supplied through the clock-setting capability; before any value
is set, the logical clock reads 1970-01-01T00:00:00.000Z. The server never reads
the host wall clock for business preconditions.

All timestamps emitted by the system are ISO-8601 UTC values with three fractional
digits (PRD §1, §2.4).
"""
from datetime import datetime, timezone, timedelta


_EPOCH = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO-8601 UTC string into an aware datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    """Logical clock; defaults to the Unix epoch until explicitly set."""

    def __init__(self):
        self.now = _EPOCH

    def reset(self):
        self.now = _EPOCH

    def set(self, dt):
        self.now = dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_days_between(start, end):
    """Floor of the day difference (end exclusive). Negative differences floored too."""
    delta = end - start
    total_seconds = delta.total_seconds()
    # floor division toward negative infinity, in whole days
    import math
    return math.floor(total_seconds / 86400.0)
