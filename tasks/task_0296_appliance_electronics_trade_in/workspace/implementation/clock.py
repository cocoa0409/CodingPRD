"""Logical clock (PRD 2.10).

The server's notion of "now" is driven by an administrative test endpoint
(`POST /_clock/set_current_utc`). Until set, it tracks real wall-clock UTC.
All price-lock expiry, promo-window, and slot-timing comparisons are evaluated
against this logical clock.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._override = None  # datetime (aware, UTC) or None

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def set(self, dt):
        # dt must be a timezone-aware datetime in UTC
        self._override = dt

    def reset(self):
        self._override = None


clock = Clock()
