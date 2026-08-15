"""ISO 8601 UTC time helpers.

All timestamps the system emits are ISO 8601 UTC with three fractional
digits, e.g. ``2026-08-01T00:00:00.000Z`` (PRD Section 2.4).
"""

from datetime import datetime, date, timezone


def parse_datetime(value):
    """Parse an ISO8601 string (accepts trailing Z, offsets, date-only).

    Returns an aware UTC datetime, or None when unparseable.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith(("Z", "z")):
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


def fmt(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
