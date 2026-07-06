"""Logical clock. Starts at 2026-03-01T00:00:00Z. Never reads wall clock."""
from datetime import datetime, timezone, timedelta

# Fixed default at process start per PRD 2.10.
_DEFAULT_ISO = "2026-03-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO-8601 UTC timestamp. Accepts trailing 'Z' or '+00:00'."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    s2 = s
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except Exception as e:
        raise ValueError(f"invalid iso8601: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_DEFAULT_ISO)
        # Monotonic sequence to break ties in "same millisecond" ordering per PRD 2.3.
        self._seq = 0

    def now(self):
        return self._now

    def next_seq(self):
        self._seq += 1
        return self._seq

    def format(self, dt=None):
        """Format a UTC datetime to ISO-8601 with three fractional digits, Z suffix."""
        if dt is None:
            dt = self._now
        # Force millisecond precision.
        micros = dt.microsecond
        millis = micros // 1000
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        return f"{base}.{millis:03d}Z"

    def now_iso(self):
        return self.format(self._now)

    def set_from_iso(self, iso_str):
        dt = _parse_iso(iso_str)
        self._now = dt

    def add(self, **kwargs):
        self._now = self._now + timedelta(**kwargs)


clock = LogicalClock()


def parse_iso(s):
    return _parse_iso(s)
