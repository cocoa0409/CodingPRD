"""Logical clock and ISO-8601 helpers.

The system runs on a logical clock (PRD §2.8). It starts at real wall-clock UTC
on boot and is set/advanced by the test-driving clock endpoints. Timestamps in
responses use the *real* server time for created_at/updated_at metadata, while
the logical clock governs hold expiry, slot cutoffs, and staged_at.
"""

from datetime import datetime, timezone, timedelta


def now_iso():
    """Real server time, ISO 8601 UTC, three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO-8601 instant into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ValueError("invalid timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def now_iso(self):
        return _fmt(self._now)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
