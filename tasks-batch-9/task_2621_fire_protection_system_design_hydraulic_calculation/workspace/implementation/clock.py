"""The logical clock (PRD 2.10).

All time in the service comes from this clock, never from wall-clock time.  At
startup it reads exactly 2026-08-01T00:00:00Z and it must not fall back to the
host's real time under any circumstance.
"""
from datetime import datetime, timezone

from utils import fmt_dt

STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = STARTUP_UTC


def reset():
    global _current
    _current = STARTUP_UTC


def now():
    return _current


def now_iso():
    return fmt_dt(_current)


def set_now(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current
