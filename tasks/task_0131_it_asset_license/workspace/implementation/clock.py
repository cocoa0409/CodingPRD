"""Server-controlled logical wall clock (PRD 2.4).

Every time-dependent rule reads this clock, never real wall-clock time.
A test advances it via POST /assets/_clock/set_current_utc. State is module
level so it wipes on every fresh process boot (per-test-server isolation).
"""
from datetime import datetime, timezone

# Logical "now" the server uses for all time-dependent evaluation.
# Defaults to the real current UTC instant until a test sets it; in practice
# tests set it explicitly before exercising any time-dependent rule.
_current = datetime.now(timezone.utc)


def get_now():
    """Return the current server-clock instant as a tz-aware UTC datetime."""
    return _current


def set_now(dt):
    """Set the server clock to the supplied tz-aware UTC datetime."""
    global _current
    _current = dt
