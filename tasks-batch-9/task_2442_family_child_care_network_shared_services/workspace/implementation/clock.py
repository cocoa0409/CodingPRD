"""The server-controlled logical clock (PRD 2.5).

Before the clock is ever set it reads exactly 2026-08-01T00:00:00Z.  It never
falls back to the host's wall-clock time.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_RAW = "2026-08-01T00:00:00Z"

_state = {"raw": DEFAULT_RAW, "dt": datetime(2026, 8, 1, tzinfo=timezone.utc)}


def parse_instant(value):
    """Parse an ISO 8601 instant or a bare YYYY-MM-DD date.  None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_now(raw, dt):
    _state["raw"] = raw
    _state["dt"] = dt


def now():
    """The logical clock instant."""
    return _state["dt"]


def now_raw():
    """The logical clock instant exactly as it was supplied."""
    return _state["raw"]


def today():
    """The date part of the logical clock."""
    return _state["dt"].date()


def date_of(value):
    """The date part of a stored/supplied instant string."""
    dt = parse_instant(value)
    return None if dt is None else dt.date()


def month_of(value):
    d = date_of(value)
    return None if d is None else "%04d-%02d" % (d.year, d.month)


def clock_month():
    d = today()
    return "%04d-%02d" % (d.year, d.month)


def format_date(d):
    """Render a date as a UTC-midnight instant."""
    return d.strftime("%Y-%m-%dT00:00:00.000Z")


def plus_days(d, days):
    return d + timedelta(days=days)
