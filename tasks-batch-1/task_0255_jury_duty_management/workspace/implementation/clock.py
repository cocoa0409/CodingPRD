"""Server-managed logical clock (PRD §2.8).

Temporal gates (check-in report-date lower bound, FTA-before-report-date, and the
current-year input to the age check) read 'now' from this logical clock rather
than the host wall clock, so behavior is reproducible. A JuryAdministrator sets
it via POST /_clock/set_current_utc. It starts at the real UTC instant of boot.
"""
from datetime import datetime, timezone

_current = None  # datetime (tz-aware UTC) when explicitly set; None => use wall clock


def now():
    """Return the current logical instant as a tz-aware UTC datetime."""
    if _current is not None:
        return _current
    return datetime.now(timezone.utc)


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def current_year():
    return now().year
