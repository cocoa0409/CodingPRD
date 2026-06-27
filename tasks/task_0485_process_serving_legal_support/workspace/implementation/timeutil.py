"""Datetime parsing/formatting helpers for ISO 8601 UTC instants."""
from datetime import datetime, timedelta, timezone

from errors import err


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 string" % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)
