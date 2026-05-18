"""In-memory data store — see PRD §2.7 (logical time) and §2.4 (common fields).

Everything lives in process memory. The store carries top-level dicts keyed
by entity id. Cross-entity relationships are referenced by id, never by
embedding. A single RLock guards mutation; the API does not exercise true
multi-threaded write contention but the lock makes side-effect cascades
atomic against any concurrent reads.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _WallClock:
    """Wall-clock that emits strictly monotonic ISO timestamps.

    This is unrelated to the platform's logical day index (Platform.clock_day_index)
    which is advanced only via POST /platforms/{id}/advance_clock. It exists solely
    to populate `created_at` / `updated_at` and the response envelope's
    `api_request_timestamp` with deterministic ordering.
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
    """All entities held in memory keyed by id, plus the wall clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _WallClock()

        # Entity tables: id -> dict
        self.platforms = {}
        self.borrowers = {}
        self.plaid_snapshots = {}
        self.loan_listings = {}
        self.investors = {}
        self.investments = {}
        self.loans = {}
        self.installments = {}
        self.payments = {}
        self.disclosures = {}
        self.compliance_officers = {}

    def now(self) -> datetime:
        return self.clock.now()

    # ── Convenience iterators ──────────────────────────────────────────────

    def borrowers_for_platform(self, platform_id: str):
        return [b for b in self.borrowers.values() if b.get("platform_id") == platform_id]

    def listings_for_borrower(self, borrower_id: str):
        return [l for l in self.loan_listings.values() if l.get("borrower_id") == borrower_id]

    def investments_for_listing(self, listing_id: str):
        return [i for i in self.investments.values() if i.get("listing_id") == listing_id]

    def installments_for_loan(self, loan_id: str):
        return [i for i in self.installments.values() if i.get("loan_id") == loan_id]

    def loans_for_borrower(self, borrower_id: str):
        return [l for l in self.loans.values() if l.get("borrower_id") == borrower_id]


# Singleton store used throughout the app.
store = DataStore()
