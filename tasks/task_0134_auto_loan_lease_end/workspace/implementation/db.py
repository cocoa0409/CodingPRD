"""In-memory data store for the Auto Loan & Lease End API.

All entities held in memory keyed by id. A simple wall-clock is used
for created_at / updated_at timestamps (PRD §2.4); the business clock
that drives payment due dates and lease maturity is the per-customer
`clock_day_index` integer (PRD §2.9), maintained directly on the
Customer entity and advanced via POST /customers/{id}/clock/advance.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _WallClock:
    """Monotonic wall-clock for timestamp stamping.

    Each call to now() returns a strictly later datetime so that
    created_at / updated_at remain orderable across rapid mutations.
    """

    def __init__(self):
        now = datetime.now(timezone.utc)
        anchor = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        self._logical = anchor
        self._tick = 0

    def now(self) -> datetime:
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)


class DataStore:
    """All entities held in memory, keyed by id."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _WallClock()

        # id -> entity dict
        self.customers = {}
        self.vehicles = {}
        self.loan_contracts = {}
        self.lease_contracts = {}
        self.payments = {}
        self.gap_riders = {}
        self.lease_end_assessments = {}
        self.delinquency_events = {}
        self.clock_events = {}

        # vin uniqueness index
        self.vins = set()

    def now(self) -> datetime:
        return self.clock.now()

    def reset(self) -> None:
        """Wipe all in-memory state (used by /__test__/reset only)."""
        with self.lock:
            self.customers.clear()
            self.vehicles.clear()
            self.loan_contracts.clear()
            self.lease_contracts.clear()
            self.payments.clear()
            self.gap_riders.clear()
            self.lease_end_assessments.clear()
            self.delinquency_events.clear()
            self.clock_events.clear()
            self.vins.clear()


store = DataStore()
