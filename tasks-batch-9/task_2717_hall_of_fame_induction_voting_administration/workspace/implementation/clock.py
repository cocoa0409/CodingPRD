"""The logical election clock (PRD 2.4).

Nothing in this service reads the host machine's wall clock.  Before any caller
moves it, the logical clock reads exactly 2026-08-01T00:00:00Z and it never
falls back to wall-clock time under any circumstance.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(instant):
    _state["now"] = instant


def reset():
    _state["now"] = DEFAULT_NOW


def fmt(instant):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def parse(value):
    """Parse an ISO 8601 timestamp.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
