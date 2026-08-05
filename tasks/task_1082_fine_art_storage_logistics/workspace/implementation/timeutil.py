"""Datetime parsing / formatting helpers."""
import math
from datetime import datetime, timezone

from errors import err


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Raises ERR_VALIDATION when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_format(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def now_wall():
    return datetime.now(timezone.utc)


def days_ceil(start_dt, end_dt):
    """Number of 24h days from start to end, rounding any partial day up."""
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))
