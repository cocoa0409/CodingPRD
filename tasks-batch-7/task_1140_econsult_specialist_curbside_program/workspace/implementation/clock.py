"""Server-maintained logical clock (PRD section 2.5).

Defaults to exactly 2026-05-01T00:00:00Z at startup and never falls back to
wall-clock time. Only POST /econsult/_clock/set_current_utc advances it.
"""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now = _DEFAULT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 string to a tz-aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
