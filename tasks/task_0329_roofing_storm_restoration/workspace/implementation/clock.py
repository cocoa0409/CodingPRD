"""Logical UTC clock.

The server maintains a single logical clock (PRD §2.4). It defaults to the real
wall clock until a test sets it via POST /_clock/set with field `to_iso8601`.
Warranty start_at stamps it, cancellation measures elapsed months against it,
and expiry compares against it.

State lives on a module-level object so it resets to real-time on every fresh
process boot (per-test-server isolation).
"""
from datetime import datetime, timezone


class _Clock:
    def __init__(self):
        # When None, "now" follows the real wall clock.
        self._override = None

    def set(self, dt):
        self._override = dt

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)


clock = _Clock()
