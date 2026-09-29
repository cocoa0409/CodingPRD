"""Logical clock (PRD Section 2.5).

Before any call to POST /_clock/set_current_utc the logical clock reads exactly
2026-08-01T00:00:00Z; it never falls back to real wall-clock time.
"""
import re
from datetime import datetime, timezone, timedelta

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_NOW


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def iso_now():
    return iso(now())


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_date_string(value):
    return isinstance(value, str) and bool(_DATE_RE.match(value)) and parse_dt(value + "T00:00:00Z") is not None


def date_of(dt):
    """Calendar date (YYYY-MM-DD, UTC) of an instant."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def elapsed_days(start, end):
    """Whole number of complete 86,400-second days between two instants."""
    return int((end - start).total_seconds() // 86400)
