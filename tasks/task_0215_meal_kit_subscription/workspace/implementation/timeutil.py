"""ISO 8601 UTC time helpers (PRD §2.4, §2.7).

Timestamps are ISO 8601 UTC with three fractional digits (milliseconds).
"""
from datetime import datetime, timezone, timedelta


def now_iso(dt=None):
    """Format a datetime as ISO 8601 UTC with millisecond precision and Z."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset, with or without fractional
    seconds. Returns None if the input is not a parseable string.
    """
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try a plain date (YYYY-MM-DD).
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_of(dt):
    """Return the calendar date (date object) of an aware datetime, in UTC."""
    return dt.astimezone(timezone.utc).date()
