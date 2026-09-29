"""Server-held logical clock (PRD 2.4).

Before any client sets it the logical clock reads exactly 2026-08-01T00:00:00Z and
it never falls back to real wall-clock time.
"""

from datetime import datetime, date, timedelta

from errors import fail

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, 0)

_state = {"now": DEFAULT_INSTANT}


def reset():
    _state["now"] = DEFAULT_INSTANT


def now():
    """Current logical instant (naive UTC datetime)."""
    return _state["now"]


def today():
    """Current logical date (UTC calendar date of the logical instant)."""
    return _state["now"].date()


def set_now(dt):
    _state["now"] = dt


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(_state["now"])


def parse_instant(value, error_id="ERR_INVALID_REQUEST"):
    """Parse an ISO 8601 instant, tolerating 'Z' and explicit offsets."""
    if not isinstance(value, str) or not value.strip():
        fail(error_id, "invalid timestamp")
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            fail(error_id, "invalid timestamp: %s" % raw)
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def parse_date(value, error_id="ERR_INVALID_REQUEST"):
    """Parse a strict ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        fail(error_id, "invalid date")
    txt = value.strip()
    if len(txt) != 10 or txt[4] != "-" or txt[7] != "-":
        fail(error_id, "invalid date: %s" % value)
    try:
        return date(int(txt[0:4]), int(txt[5:7]), int(txt[8:10]))
    except Exception:
        fail(error_id, "invalid date: %s" % value)


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, n):
    return d + timedelta(days=n)


def days_between(later, earlier):
    """Whole days from earlier to later (may be negative)."""
    return (later - earlier).days
