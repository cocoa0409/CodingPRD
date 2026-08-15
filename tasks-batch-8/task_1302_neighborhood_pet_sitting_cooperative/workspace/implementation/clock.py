"""Logical clock. Defaults to 2026-08-01T00:00:00Z and never falls back to
wall-clock time; advanced only via POST /coop/_clock/set_current_utc."""

from datetime import datetime, timezone

_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt
