"""Logical clock. Starts at exactly 2026-08-01T00:00:00Z; never wall-clock."""

from datetime import datetime, timezone

DEFAULT_RAW = "2026-08-01T00:00:00Z"

_state = {
    "raw": DEFAULT_RAW,
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
}


def parse_dt(value):
    """Parse an ISO 8601 datetime string; returns tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if not t:
        raise ValueError("empty")
    iso = t[:-1] + "+00:00" if t.endswith(("Z", "z")) else t
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_raw():
    return _state["raw"]


def now_dt():
    return _state["dt"]


def now_date():
    return _state["dt"].date()


def set_clock(raw):
    dt = parse_dt(raw)
    _state["raw"] = raw
    _state["dt"] = dt
    return raw
