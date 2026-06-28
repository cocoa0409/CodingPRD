"""Logical server clock.

PRD 2.4: "The clock starts at exactly 2026-01-01T00:00:00Z at startup and stays
at that value until it is explicitly advanced; it never falls back to wall-clock
time." Timestamps stamped from this clock: specimen collected_at_utc, manifest
picked_up_at_utc, manifest accession_due_utc.
"""
from datetime import datetime, timezone, timedelta

# Fixed logical clock default at process startup. Wiped/reset on every boot
# because this module is freshly imported by each new process.
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def plus_hours(self, hours):
        return self._now + timedelta(hours=hours)


clock = LogicalClock()


def to_iso_z(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits and a Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
