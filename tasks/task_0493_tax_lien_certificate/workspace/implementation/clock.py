"""Logical clock (PRD §2.4).

At server startup the clock reads exactly 2026-01-01T00:00:00Z, and before any
clock-setting call it holds that default and never falls back to wall-clock time.
Every accrual, scheduling check, and deadline reads this clock.
"""
from datetime import datetime, timezone

_DEFAULT = "2026-01-01T00:00:00Z"

# Module-level state. Starts at the documented default on every boot.
_current = None  # aware UTC datetime


def parse_iso(s):
    """Parse an ISO 8601 instant (accepts trailing Z) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def reset():
    global _current
    _current = parse_iso(_DEFAULT)


def set_current(iso_str):
    global _current
    _current = parse_iso(iso_str)
    return _current


def now():
    """Return the current logical clock as an aware UTC datetime."""
    if _current is None:
        reset()
    return _current


reset()
