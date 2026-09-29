"""Logical clock (PRD 2.5).

The server keeps a logical UTC instant.  On boot it is exactly
2026-08-01T00:00:00Z.  It NEVER falls back to the wall clock.
"""

from datetime import date, datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def reset():
    _state["now"] = DEFAULT_NOW


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(_state["now"])


def today():
    return _state["now"].astimezone(timezone.utc).date()


def today_str():
    return today().isoformat()


def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def add_days(day, n):
    return day + timedelta(days=n)


def date_str(day):
    return day.isoformat()
