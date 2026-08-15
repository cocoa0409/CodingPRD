"""The shop's logical clock (PRD section 2.5).

Startup default is exactly 2026-08-01T00:00:00Z. The clock never falls back
to wall-clock time; it only moves when a ShopManager sets it via
POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt
