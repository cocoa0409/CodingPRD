"""Logical clock -- the service's only time source.

Startup value is mandated: 2026-08-01T00:00:00Z. It may be moved forward or
backward by POST /_clock/set_current_utc; moving it touches no stored row and
bumps no version.
"""
from datetime import datetime, timezone, timedelta

INITIAL_UTC = "2026-08-01T00:00:00Z"

_state = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a calendar date (YYYY-MM-DD) or a full instant into a UTC datetime."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parse_iso(raw)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    return _state["now"]


def now_iso():
    return format_instant(_state["now"])


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def current_year():
    return _state["now"].year


def days_between(start, end):
    """Whole days from start up to end (may be negative)."""
    return (end - start).days


DAY = timedelta(days=1)
