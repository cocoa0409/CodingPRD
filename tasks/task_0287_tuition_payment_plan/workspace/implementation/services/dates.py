"""Date / clock arithmetic. All 'now' reads the institution-scoped clock_utc.

PRD §2.4: the logical clock is the ONLY source of 'now'; never wall-clock.
On institution creation clock_utc begins at the Unix epoch.
"""
from datetime import datetime, timezone, timedelta

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """Serialize an aware datetime to ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def day_number(dt):
    """Whole-day value of a datetime: integer count of whole days since epoch.

    Used for whole-day comparisons (due_date + grace, days_late, days_elapsed).
    """
    delta = dt - EPOCH
    return delta.days


def add_days(dt, n):
    return dt + timedelta(days=n)
