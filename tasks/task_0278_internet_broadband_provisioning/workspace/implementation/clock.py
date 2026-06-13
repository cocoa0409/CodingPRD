"""Controllable logical clock (PRD §3.12).

An administrative capability pins the server clock to a supplied UTC instant
given as `to_iso8601`. Once set, every field stamped with "the current instant"
reads from this pinned clock. Until pinned, the clock follows wall time.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._pinned = None  # datetime (tz-aware UTC) or None

    def set_now(self, dt):
        self._pinned = dt

    def now(self):
        if self._pinned is not None:
            return self._pinned
        return datetime.now(timezone.utc)


_clock = Clock()


def get_clock():
    return _clock
