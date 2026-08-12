"""Logical clock. Startup default is exactly 2026-05-01T00:00:00Z and it never
falls back to wall-clock time. All time-dependent behavior reads this clock."""

from datetime import datetime, timezone

_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = _START


def now():
    return _now


def set_now(value):
    global _now
    _now = value


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z.
    Used only for created_at / updated_at / api_request_timestamp (PRD §2.2, §2.10)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_seconds(dt):
    """ISO 8601 UTC at whole-second precision, e.g. 2026-05-01T00:00:00Z.
    Used for business datetimes (due_at, due_date, abandon_effective_date,
    ballot window, session windows, effective/expiration dates, the logical
    clock readout) per PRD §2.9 and §2.12."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 datetime. Returns aware UTC datetime or None if invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
