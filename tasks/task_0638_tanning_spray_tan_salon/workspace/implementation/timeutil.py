"""ISO 8601 UTC timestamp helpers (PRD §2.4 / §2.5).

Timestamps are ISO 8601 UTC with three fractional digits (milliseconds),
suffixed with 'Z'. Parsing accepts a broad range of ISO inputs (with or
without fractional seconds, with 'Z' or +00:00 offsets, and bare dates).
"""
from datetime import datetime, timezone, date


def to_iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # milliseconds = first 3 digits of microseconds
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable string.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to an explicit UTC offset for fromisoformat.
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try bare date form (YYYY-MM-DD).
        try:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
