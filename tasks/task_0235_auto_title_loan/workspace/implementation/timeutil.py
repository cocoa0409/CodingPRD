"""ISO 8601 UTC datetime helpers.

PRD 2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from datetime import datetime, timezone, timedelta

from errors import err


def iso_now(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts trailing 'Z' and optional fractional seconds. Raises ERR_INVALID_REQUEST
    when the value is not a well-formed datetime string.
    """
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "datetime must be a string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "malformed datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)
