"""The logical clock (PRD 2.4).

Time in this system is a logical clock, not wall-clock time. On a cold start it
reads exactly 2026-08-01T00:00:00Z and it never falls back to the host's real
time. Every server-stamped instant is read from here.
"""

from datetime import datetime, timezone

COLD_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = COLD_START


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = COLD_START


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_current)


def parse(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
