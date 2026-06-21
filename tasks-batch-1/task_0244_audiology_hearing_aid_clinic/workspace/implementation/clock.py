"""Server-held logical clock (PRD §3.11).

All temporal logic — trial deadlines, benefit period ends, warranty windows,
cycle due dates — is evaluated against this logical clock rather than wall
time. A ClinicAdmin sets it via POST /clinic/_clock/set with a to_iso8601
instant. Until it is set, the clock falls back to real UTC now so the server
is usable on a fresh boot.
"""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = None  # None => fall back to real wall-clock UTC

    def now(self):
        """Return the current logical instant as an aware UTC datetime."""
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._now = dt


clock = Clock()
