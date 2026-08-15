"""Logical clock for the rack pricing server.

The server keeps its own logical clock. On startup it reads
2026-08-01T00:00:00Z and does NOT track wall-clock time; only
POST /rack/_clock/set_current_utc advances it.
"""
from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def fmt_iso(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return fmt_iso(clock.now())


def today_str():
    return clock.now().date().isoformat()


def clock_iso():
    """Canonical rendering of the logical clock for the clock endpoint.

    Whole-second values render without a fractional part so that a caller
    who set '2026-08-15T00:00:00Z' reads the same string back.
    """
    n = clock.now()
    if n.microsecond == 0:
        return n.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_iso(n)


def parse_iso(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z or numeric offset).

    Returns an aware UTC datetime, or None when unparseable.
    """
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None
