"""Logical clock.

PRD 3.11: the server clock starts at a fixed default of midnight UTC on
2026-01-01 and, until explicitly set, reads exactly that default and never
falls back to wall-clock time. Operators advance it via
POST /_clock/set_current_utc with a to_iso8601 value.

The clock is per-process module-level state. A fresh process resets it to the
default — which is exactly what per-test-server isolation expects.
"""
from datetime import datetime, timezone

DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def reset():
    global _now
    _now = DEFAULT
