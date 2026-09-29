"""The logical clock and whole-day instant arithmetic (PRD 2.5).

The service never reads wall-clock time.  Before any operator moves it the
logical clock reads exactly 2026-08-01T00:00:00Z; it may be moved forwards or
backwards freely, and moving it mutates no entity.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
DAY_SECONDS = 86400

_now = DEFAULT_CLOCK


def reset():
    global _now
    _now = DEFAULT_CLOCK


def now():
    return _now


def set_now(value):
    global _now
    _now = value


def stamp():
    """The logical clock rendered in the wire format."""
    return fmt(_now)


def fmt(value):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse(text):
    """Parse an ISO 8601 instant, returning None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def plus_days(value, days):
    return value + timedelta(seconds=DAY_SECONDS * days)


def whole_days_between(start, end):
    """Elapsed whole 86400-second days from start to end, remainder discarded."""
    return int((end - start).total_seconds() // DAY_SECONDS)
