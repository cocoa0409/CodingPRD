"""Shared helpers: ids, datetime parsing/formatting, month arithmetic, name normalization.

All datetimes handled by the API are ISO 8601 UTC values with second precision.
created_at / updated_at / event timestamps are all read from the logical clock.
"""
import calendar
import re
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime truncated to
    whole seconds. Returns None when the value is not a parseable datetime."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt):
    """Serialize an aware datetime as ISO 8601 UTC with second precision."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_ms(dt):
    """Serialize with three fractional digits (used for the meta request timestamp)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(dt, months):
    """Add calendar months, preserving the day-of-month (clamped to month length)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


_NORMALIZE_STRIP = re.compile(r"[^A-Z0-9 ]")
_NORMALIZE_SPACES = re.compile(r" +")


def normalize_name(s):
    """uppercase -> remove every char not in [A-Z0-9 space] -> collapse spaces -> trim"""
    if s is None:
        return None
    s = s.upper()
    s = _NORMALIZE_STRIP.sub("", s)
    s = _NORMALIZE_SPACES.sub(" ", s).strip()
    return s
