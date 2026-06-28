"""The single server-controlled logical clock (PRD §2.9, §3.11).

Starts at exactly 2026-01-01T00:00:00Z on every boot and never falls back to
wall-clock time. Advanced only via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def iso(self):
        return _to_iso(self._now)


def _to_iso(dt):
    # ISO 8601 UTC with three fractional digits, 'Z' suffix.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = Clock()
