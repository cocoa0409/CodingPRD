"""The logical clock (PRD §2.4).

Startup value is exactly 2026-08-01T00:00:00Z and the clock never falls back to
wall-clock time.  Every deadline, decay factor, permit window, expiry sweep,
review-window lapse check and elapsed-processing metric reads this clock.
"""
import math
from datetime import datetime, timezone, timedelta

_CURRENT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _CURRENT


def set_now(dt):
    global _CURRENT
    _CURRENT = dt.astimezone(timezone.utc)
    return _CURRENT


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    """Real-time stamp used only for the response envelope's meta block."""
    return fmt(datetime.now(timezone.utc))


def parse_iso8601(value):
    """Parse an ISO 8601 instant, returning an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def whole_days(later, earlier):
    """Whole elapsed days between two instants, discarding any partial day."""
    return math.floor((later - earlier).total_seconds() / 86400.0)


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_365_day_blocks(later, earlier):
    return math.floor((later - earlier).total_seconds() / (365.0 * 86400.0))
