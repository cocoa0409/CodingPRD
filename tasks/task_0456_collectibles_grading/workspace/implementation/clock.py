"""Logical clock (PRD §3.12).

Startup default is 2026-01-01T00:00:00Z; the clock never falls back to
wall-clock time. Settable via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

# Logical clock instant, stored as a timezone-aware UTC datetime.
_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    # dt is timezone-aware UTC
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(millis)


def now_iso():
    """Current logical-clock instant as an ISO 8601 string (3 fractional digits)."""
    return _format_iso(_now)


def now_dt():
    return _now


def set_now(iso_string):
    """Set the logical clock from an ISO 8601 string carried in `to_iso8601`."""
    global _now
    s = iso_string.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _now = dt


def reset():
    global _now
    _now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
