"""The logical program clock (PRD 2.5).

Before the clock is set for the first time it reads exactly
2026-08-01T00:00:00Z, and once set it never falls back to real wall-clock time.
No other module may consult ``datetime.now()``.
"""

from datetime import datetime, timezone

_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _EPOCH


def reset():
    global _current
    _current = _EPOCH


def now():
    """Current logical instant as a timezone-aware UTC datetime."""
    return _current


def set_now(instant):
    global _current
    _current = instant.astimezone(timezone.utc)
    return _current


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if instant is None:
        return None
    dt = instant.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_current)
