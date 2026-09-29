"""Logical clock.

PRD 2.5: the service never reads wall-clock time.  Before any call to
POST /_clock/set_current_utc the logical clock reads exactly
2026-08-01T00:00:00Z, and there is no fallback to real time.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class _Clock(object):
    def __init__(self):
        self._now = DEFAULT_NOW

    @property
    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)

    def iso(self):
        return fmt_instant(self._now)

    def date(self):
        return self._now.date()

    def iso_date(self):
        return self._now.date().isoformat()


clock = _Clock()
