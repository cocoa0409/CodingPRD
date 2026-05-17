"""In-memory data store + logical clock."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """PRD §2.9: 'the system is fully deterministic against a server-side
    logical clock, advanced only through the platform-admin test-driving
    capability'.

    The clock is purely logical: it is anchored once at process start
    (or test reset) and advances only via explicit /_clock/advance
    calls. It does NOT track real wall time between calls, so that
    deterministic test assertions about delinquency_days, end_date
    crossings, scheduled_date crossings, and noi_sent_at windows hold
    regardless of how long the test takes to execute.
    """
    def __init__(self):
        # Anchor at UTC midnight of today so that:
        #   * tests that send origination_date = "today at UTC midnight"
        #     observe next_due_date = origination + 1 month at midnight,
        #     and after advance(N) the server-side now() is exactly
        #     midnight + N days — making delinquency arithmetic
        #     unambiguous integer-day math.
        #   * cumulative timestamps still strictly increase (each call
        #     to now() returns the anchor + tiny monotonic nanosecond
        #     bumps so created_at / updated_at remain distinguishable).
        now = datetime.now(timezone.utc)
        self._logical = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        # Return logical midnight + tiny monotonic tick so each call is
        # strictly distinguishable for created_at / updated_at ordering,
        # but the date component is exactly the logical calendar day.
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def advance_days(self, days: int) -> None:
        if days < 0:
            raise ValueError("days must be non-negative")
        self._logical = self._logical + timedelta(days=days)
        # Reset tick on advance so we re-base from the new midnight.
        self._tick = 0


def _seconds_to_delta(seconds: float):
    from datetime import timedelta
    return timedelta(seconds=seconds)


class DataStore:
    """In-memory database for all entities + the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Each map: id -> dict
        self.borrowers = {}
        self.loans = {}
        self.payments = {}
        self.escrow_analyses = {}
        self.disbursements = {}
        self.forbearance_plans = {}
        self.pmi_requests = {}
        self.foreclosure_cases = {}
        self.mediation_cases = {}

        # Per-mediation-case audit: who extended each offer (for SoD on /complete).
        self.last_offer_extender = {}  # mediation_case_id -> X-User-ID

    # ── Convenience accessors ──────────────────────────────────────────────

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used throughout the app.
store = DataStore()
