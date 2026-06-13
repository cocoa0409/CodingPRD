"""Deterministic test-driving server clock (PRD §3.12).

The server's notion of "now" is set by POST /_clock/set_current_utc and used for
all age, release-window, and trailing-365-day evaluations. Defaults to real UTC
until a clock instant has been set.
"""
from datetime import datetime, timezone

_now_override = None  # datetime (tz-aware UTC) or None


def set_now(dt):
    global _now_override
    _now_override = dt


def now():
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def reset():
    global _now_override
    _now_override = None
