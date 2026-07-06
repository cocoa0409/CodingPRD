"""Logical clock (PRD §2.7).

On startup the clock reads exactly 2026-03-01T00:00:00Z and, until explicitly
set, stays at that default and never falls back to wall-clock time. Every
time-gated rule is evaluated against this logical clock.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def parse_iso8601(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_now(iso_str):
    _state["now"] = parse_iso8601(iso_str)


def now():
    return _state["now"]


def reset():
    _state["now"] = _DEFAULT
