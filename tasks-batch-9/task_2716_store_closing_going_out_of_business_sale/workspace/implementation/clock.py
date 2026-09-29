"""Logical clock (PRD 2.4). Every server-derived date/instant reads from here."""

from datetime import datetime, date, timedelta

DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0)

_state = {"now": DEFAULT_UTC, "raw": "2026-08-01T00:00:00Z"}


def parse_instant(text):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1]
    elif s.endswith("+00:00"):
        s = s[:-6]
    elif s.endswith("+0000"):
        s = s[:-5]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_date(text):
    if not isinstance(text, str):
        return None
    s = text.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def set_now(dt, raw=None):
    _state["now"] = dt
    _state["raw"] = raw


def now():
    return _state["now"]


def raw():
    return _state["raw"]


def today():
    return _state["now"].date()


def iso_instant(dt=None):
    """ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        dt = _state["now"]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def iso_now():
    return iso_instant(_state["now"])


def iso_date(d):
    if d is None:
        return None
    return d.isoformat()


def days_between(a, b):
    """(a - b) in whole days."""
    return (a - b).days


def reset():
    _state["now"] = DEFAULT_UTC
    _state["raw"] = "2026-08-01T00:00:00Z"
