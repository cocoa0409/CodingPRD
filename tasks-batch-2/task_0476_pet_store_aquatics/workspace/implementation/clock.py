"""The logical server clock (PRD §2.11).

At server startup the clock reads exactly 2026-01-01T00:00:00Z, and before any
administrative set the clock holds precisely that default and never falls back
to real time. An administrative capability sets it for subsequent time-gated
checks.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 instant (with trailing Z or offset) to aware datetime."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, iso_value):
        self._now = _parse_iso(iso_value)


clock = Clock()


def parse_iso(value):
    return _parse_iso(value)
