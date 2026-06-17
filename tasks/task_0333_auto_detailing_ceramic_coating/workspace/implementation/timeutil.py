"""ISO 8601 UTC datetime helpers — parse, format (3 fractional digits), arithmetic."""
from datetime import datetime, timezone, timedelta


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the input is not a parseable datetime string.
    Accepts a trailing 'Z' and explicit offsets; normalizes to UTC.
    """
    if not isinstance(s, str) or not s:
        return None
    raw = s.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    return dt + timedelta(days=days)
