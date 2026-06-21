"""Datetime parsing & formatting helpers.

PRD §2.4: timestamps are ISO 8601 UTC with exactly three fractional digits,
e.g. "2025-05-24T10:30:00.123Z".
"""

from datetime import datetime, timezone, timedelta
import math


def iso(dt):
    """Format a datetime as ISO 8601 UTC with millisecond precision and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # milliseconds with three digits, trailing 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None for falsy input.
    Raises ValueError on malformed input.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def floor_days(later, earlier):
    """Whole UTC days that have fully elapsed between earlier and later.

    Partial days are truncated toward zero (PRD §2.5). Can be negative if
    later < earlier; callers clamp with max(0, ...) where required.
    """
    delta = later - earlier
    total_seconds = delta.total_seconds()
    return math.floor(total_seconds / 86400.0)
