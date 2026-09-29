"""The logical clock: the sole time source for every temporal rule (PRD 2.4)."""

import datetime as _dt

from errors import ApiError

STARTUP_INSTANT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

_now = STARTUP_INSTANT


def reset():
    global _now
    _now = STARTUP_INSTANT


def now():
    """Current logical instant as an aware UTC datetime."""
    return _now


def set_now(instant):
    global _now
    _now = instant
    return _now


def fmt(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.timezone.utc)
    instant = instant.astimezone(_dt.timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def now_iso():
    return fmt(_now)


def parse(value):
    """Parse an ISO 8601 instant. Returns None when the value is unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def parse_required(value, error_id="ERR_INVALID_REQUEST"):
    parsed = parse(value)
    if parsed is None:
        raise ApiError(error_id)
    return parsed


def wall_now_iso():
    return fmt(_dt.datetime.now(_dt.timezone.utc))
