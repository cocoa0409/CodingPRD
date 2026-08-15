"""Server-maintained logical clock (PRD §2.4).

The clock starts at exactly 2026-08-01T00:00:00Z, moves only when a
ComplianceOfficer calls the clock endpoint, and never falls back to
wall-clock time.
"""

from datetime import datetime, timezone

_DEFAULT = "2026-08-01T00:00:00Z"

_current = datetime(2026, 8, 1, tzinfo=timezone.utc)


def now():
    return _current


def today():
    return _current.date()


def set_to(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def format_current():
    return _current.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (_current.microsecond // 1000)
