"""Logical clock — all deadline/window/cadence comparisons read this clock.

Startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall-clock.
URDirector may advance/rewind via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _current


def set_logical_now(dt):
    global _current
    _current = dt


def parse_iso(s):
    """Parse an ISO8601 timestamp string into an aware datetime (UTC assumed when Z)."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
