"""The logical clock (PRD 2.4).

Nothing in this system consults wall-clock time. The clock begins at
2026-08-01T00:00:00Z on a fresh server and only moves when an operator sets it.
"""

from datetime import datetime, timedelta, timezone

EPOCH_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = EPOCH_START


def now():
    return _current


def set_now(value):
    global _current
    _current = value
    return _current


def reset():
    global _current
    _current = EPOCH_START


def fmt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_str():
    return fmt(_current)


def parse(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def plus_days(value, days):
    return value + timedelta(days=days)


def whole_days_between(later, earlier):
    """Floor of the elapsed seconds divided by 86,400 (may be negative)."""
    return int((later - earlier).total_seconds() // 86400)
