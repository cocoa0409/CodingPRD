"""Simulated logical clock (PRD §2.10).

The clock starts at a fixed epoch on every boot so each fresh process is
deterministic. Tests drive time via POST /_clock/set and POST /_clock/advance.
"""
from datetime import datetime, timezone, timedelta

# Default boot instant. Tests typically set the clock explicitly before any
# time-gated assertions; this is just a deterministic starting point.
_EPOCH = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _EPOCH}


def now():
    """Current simulated UTC datetime (timezone-aware)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = _EPOCH


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return to_iso(now())


def parse_iso(s):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' and optional fractional seconds. Returns None for
    inputs that are not valid datetime strings.
    """
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
