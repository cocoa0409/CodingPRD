"""Server-side logical UTC clock (PRD section 2.5).

The clock reads exactly 2026-08-01T00:00:00Z before any call is made.  It never
falls back to wall-clock time.
"""

from datetime import datetime, timezone, date, timedelta

UTC = timezone.utc
DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(UTC)


def today():
    return now().date()


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def iso_now():
    return iso(now())


def date_str(d):
    if d is None:
        return None
    return d.isoformat()


def midnight(d):
    """A date-only bound read as midnight UTC at the start of that day."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def add_days(d, days):
    return d + timedelta(days=days)
