"""Logical clock + ISO8601 helpers (PRD §2.5).

The logical clock drives every time-sensitive rule (SLA due, breach, lifecycle
timestamps). At startup it reads exactly 2026-03-01T00:00:00Z and never falls
back to host wall-clock time. The api_request_timestamp in the response envelope
(§2.2) is the only place real wall-clock time is used.
"""
from datetime import datetime, timezone, timedelta

CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


def _fmt(dt):
    """ISO8601 UTC with exactly three fractional digits, 'Z' suffix.

    Used for the audit timestamps PRD §2.2/§2.4 pin to three fractional digits:
    api_request_timestamp, created_at, updated_at.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _fmt_clock(dt):
    """ISO8601 UTC at second precision, 'Z' suffix (no fractional digits).

    Used for the logical-clock value (current_utc) and every clock-derived
    lifecycle stamp (*_iso). PRD §2.5's only worked clock example is
    `2026-03-01T00:00:00Z` (second precision); SLA due dates derive from the
    clock by whole-minute/whole-hour offsets and likewise land on exact
    seconds. Any sub-second component is dropped to match that canonical form.
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_real():
    """Real wall-clock time for response meta (§2.2). Not the logical clock."""
    return _fmt(datetime.now(timezone.utc))


def parse_iso(s):
    """Parse an ISO8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._dt = parse_iso(CLOCK_DEFAULT)

    def get(self):
        return self._dt

    def set(self, dt):
        self._dt = dt.astimezone(timezone.utc)

    def iso(self):
        """Three-fractional-digit form, for created_at/updated_at (§2.4)."""
        return _fmt(self._dt)

    def iso_clock(self):
        """Second-precision form, for current_utc and *_iso stamps (§2.5)."""
        return _fmt_clock(self._dt)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def iso(dt):
    """Second-precision form for clock-derived lifecycle *_iso values (§2.5).

    Used by sla.compute_due for response_due_iso / resolution_due_iso, which
    derive from the clock-stamped assigned_at_iso by whole-minute / whole-hour
    offsets and therefore land on exact seconds.
    """
    if dt is None:
        return None
    return _fmt_clock(dt)
