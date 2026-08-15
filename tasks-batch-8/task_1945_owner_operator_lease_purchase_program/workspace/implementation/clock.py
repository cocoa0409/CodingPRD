"""Logical clock (PRD §2.5). Starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time."""

from datetime import datetime, timezone


_INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _INITIAL


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt
    return _current


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with second precision and Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
