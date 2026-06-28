"""Logical clock (PRD Section 2.7).

The system does not read wall-clock time. It maintains a single logical clock
that defaults, at server startup, to exactly 2026-01-01T00:00:00Z; until the
clock is explicitly set, every timestamp the system mints and every time
comparison it makes uses this default, and it never falls back to real-world
time.
"""

from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def _parse_iso(s):
    """Parse an ISO 8601 UTC timestamp (accepts trailing Z or +00:00)."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso_ms(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        """Current logical-clock datetime (UTC aware)."""
        return self._now

    def now_iso_ms(self):
        """Current logical clock as ISO 8601 UTC with three fractional digits."""
        return _format_iso_ms(self._now)

    def set_from_iso(self, iso_str):
        self._now = _parse_iso(iso_str)
        return self._now

    @staticmethod
    def parse(iso_str):
        return _parse_iso(iso_str)

    @staticmethod
    def add_days(dt, days):
        return dt + timedelta(days=days)

    @staticmethod
    def format_ms(dt):
        return _format_iso_ms(dt)
