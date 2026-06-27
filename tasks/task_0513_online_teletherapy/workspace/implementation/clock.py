"""Logical clock. Startup default is 2026-05-01T00:00:00Z; never falls back to wall-clock."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_instant(dt):
    """ISO 8601 UTC with second precision (no fractional digits), e.g. 2026-05-01T00:00:00Z.

    Used for domain instant fields that derive from the logical clock or from
    operator-supplied UTC instants (e.g. current_period_start, billing-period
    boundaries, credit expiry, cancel_effective_on). The three-fractional-digit
    form (iso_millis) is reserved for the system audit timestamps created_at,
    updated_at, submitted_at, and api_request_timestamp.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
