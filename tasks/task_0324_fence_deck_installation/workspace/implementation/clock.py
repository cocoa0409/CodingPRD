"""Server logical clock (PRD §3.9 — test-driving for warranty expiry).

The clock starts at wall-clock UTC and can be overridden via
POST /_clock/set_current_utc. All timestamp generation (created_at,
updated_at, api_request_timestamp) and warranty expiry compute against
this single source so tests can drive coverage-term elapse deterministically.
"""
from datetime import datetime, timezone

_offset_target = None  # if set, the "current" UTC instant (a datetime)


def _wall_now():
    return datetime.now(timezone.utc)


def set_current_utc(dt):
    """Override the logical clock to a fixed UTC instant."""
    global _offset_target
    _offset_target = dt


def now():
    """Return the current logical UTC datetime."""
    if _offset_target is not None:
        return _offset_target
    return _wall_now()


def now_iso():
    """ISO 8601 UTC instant with exactly three fractional digits (PRD §2.4)."""
    return format_iso(now())


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 instant (accepting trailing Z) to an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    global _offset_target
    _offset_target = None
