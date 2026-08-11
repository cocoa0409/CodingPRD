"""The deterministic logical clock (PRD section 2.4).

The server never reads the wall clock for domain behaviour. The startup
default is exactly 2026-05-01T00:00:00Z; a TurnaroundManager may move it
through POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _now


def set_logical_now(dt):
    global _now
    _now = dt
