"""The logical clock (PRD section 2.5).

Before any call to POST /_clock/set_current_utc the logical clock reads exactly
2026-08-01T00:00:00Z, and it never falls back to wall-clock time.
"""
from datetime import datetime, timezone, date, timedelta

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now():
    return _now


def set_now(value):
    global _now
    previous = _now
    _now = value
    return previous


def today():
    return _now.date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_now)


def parse_datetime(value):
    """Parse an ISO 8601 datetime. Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str) or len(value.strip()) != 10:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def add_days(dt, days):
    return dt + timedelta(days=days)
