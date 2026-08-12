"""Logical clock. Startup default is exactly 2026-05-01T00:00:00Z; never wall clock."""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def now():
    """Return the current logical time as an aware UTC datetime."""
    return _current


def set_current(dt):
    global _current
    _current = dt


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts trailing 'Z' or explicit offsets. Returns None on failure.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits and Z.

    Used for `api_request_timestamp`, `created_at`, and `updated_at` — the three
    fields PRD §2.2/§2.5 explicitly pin to three fractional digits.
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_minute(dt):
    """Format an aware UTC datetime as ISO 8601 UTC at minute precision (no
    fractional digits), matching the PRD's own literal rendering of scheduling
    instants (e.g. the startup clock reading `2026-05-01T00:00:00Z`).

    Used for all domain/scheduling timestamps (`start_at`, `end_at`,
    `approval_deadline`, `confirm_by_deadline`, `active_from`, `expires_at`,
    `redeemed_at`, `sent_at`, `due_at`, `submitted_at`, `reviewed_at`,
    `cancelled_at`, `completed_at`, `current_utc`) — PRD §2.10: "Scheduling
    arithmetic is performed at minute precision and all timestamps are ISO 8601
    in UTC."
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
