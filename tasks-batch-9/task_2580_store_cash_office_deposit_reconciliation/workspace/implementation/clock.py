"""Server-held logical clock (PRD section 2.4).

On startup the clock reads exactly 2026-08-01T00:00:00Z and the server never
falls back to wall-clock time for any time-sensitive rule.
"""
from datetime import datetime, timedelta, timezone

STARTUP_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": STARTUP_INSTANT}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def plus_minutes(instant, minutes):
    return instant + timedelta(minutes=minutes)


def plus_hours(instant, hours):
    return instant + timedelta(hours=hours)


def plus_days(instant, days):
    return instant + timedelta(days=days)


def fmt(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if isinstance(instant, str):
        return instant
    inst = instant.astimezone(timezone.utc)
    return inst.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (inst.microsecond // 1000)) + "Z"


def parse(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
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


def wall_now():
    return datetime.now(timezone.utc)
