"""Server-side logical clock (PRD §2.12).

Before any client positions it the clock reads exactly 2026-08-01T00:00:00Z and
never falls back to host wall-clock time.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_UTC


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt.astimezone(timezone.utc)
    return _now


def iso_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_millis(_now)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def slot_window_start(dt):
    """Floor an instant to the nearest 10-minute boundary from the top of the hour."""
    return dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)


SLOT_WINDOW = timedelta(minutes=10)
TURNAROUND_BUFFER = timedelta(minutes=45)
