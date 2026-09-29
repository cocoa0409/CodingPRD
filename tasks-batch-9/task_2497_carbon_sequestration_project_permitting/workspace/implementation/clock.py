"""Server-wide logical clock (PRD Section 2.4).

Every timestamp the server writes and every elapsed-time / window comparison it
makes reads this clock.  It never reads the host wall clock.  A fresh process
starts the clock at exactly 2026-08-01T00:00:00Z.
"""

from datetime import datetime, timezone

from errors import ApiError

DEFAULT_CURRENT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"current": DEFAULT_CURRENT_UTC}


def reset():
    _state["current"] = DEFAULT_CURRENT_UTC


def now():
    return _state["current"]


def set_now(dt):
    _state["current"] = dt.astimezone(timezone.utc)
    return _state["current"]


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(now())


def parse_iso(raw):
    """Parse an ISO 8601 timestamp; returns a tz-aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
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


def must_parse(raw, field):
    parsed = parse_iso(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp" % field)
    return parsed
