"""Server-controlled logical clock.

Per PRD §2.4, the system runs on a server-controlled logical clock rather than
wall time. A PlatformAdmin can set the current UTC instant via POST /_clock/set.
Every time-sensitive evaluation reads this logical clock.

The clock initializes to the real wall-clock UTC at process boot, so that a fresh
server that never receives a _clock/set still produces sensible (monotonic-ish)
timestamps. Tests that care about time drive it explicitly.
"""

from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        """Return the current logical clock as a timezone-aware UTC datetime."""
        return self._now

    def set(self, dt):
        """Set the logical clock to an absolute timezone-aware UTC datetime."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._now = dt.astimezone(timezone.utc)
        return self._now


clock = Clock()
