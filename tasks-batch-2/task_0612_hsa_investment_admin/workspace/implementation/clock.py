"""The logical server clock (PRD §3.11).

At server startup the clock reads exactly 2026-01-01T00:00:00Z and only moves
via POST /_clock/set_current_utc. It governs posted_at stamping and all
date-derived fields. Wall-clock time is never consulted for domain timestamps.

Note: created_at / updated_at / api_request_timestamp are governed by the
logical clock as well (PRD §1: "A single logical server clock ... governs every
date-derived field and stamp").
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = self._parse(DEFAULT_CLOCK_ISO)

    @staticmethod
    def _parse(iso):
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def set(self, iso):
        self._dt = self._parse(iso)

    def now(self):
        return self._dt

    def now_iso(self):
        """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
        dt = self._dt
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = LogicalClock()
