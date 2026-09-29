"""The logical compliance clock (PRD 2.5).

Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z.
It never falls back to real wall-clock time.
"""

from datetime import datetime, timezone, date

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = to_utc(dt)


def to_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = to_utc(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(now())


def today():
    return now().date()


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
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
        return None
    return to_utc(dt)


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None
