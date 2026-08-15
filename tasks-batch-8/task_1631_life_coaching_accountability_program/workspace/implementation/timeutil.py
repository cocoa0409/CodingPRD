"""Time helpers. All timestamps derive from the logical clock (PRD §2.5):
ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4).
"""
from datetime import date, datetime, timezone

from db import store


def now():
    """Current logical time (datetime, tz-aware UTC)."""
    return store.clock


def today():
    return store.clock.date()


def fmt_dt(dt):
    """datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ'"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat()


def now_iso():
    return fmt_dt(store.clock)


def parse_datetime(v):
    """Parse an ISO 8601 datetime; returns tz-aware UTC datetime or None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(v):
    """Parse an ISO 8601 date (YYYY-MM-DD); returns date or None."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    try:
        return date.fromisoformat(s[:10]) if len(s) >= 10 else date.fromisoformat(s)
    except ValueError:
        return None
