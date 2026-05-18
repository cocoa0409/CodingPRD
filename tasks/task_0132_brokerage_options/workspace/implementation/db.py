"""In-memory data store + logical clock.

PRD §2.6 specifies a server-side logical clock that is advanced solely
through the test-only admin endpoint /brokerage/_clock/advance. The
process initialises the clock to a fixed UTC midnight (today's date) so
all timestamps are deterministic across test runs.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """Server-controlled logical clock.

    `now()` returns the clock's anchor + a monotonic microsecond tick so
    that every call yields a strictly-increasing distinguishable
    timestamp (preserves created_at ordering in mass mutations) while
    the calendar-date component remains the deterministic anchor date.

    `advance_seconds(n)` jumps the anchor forward by n whole seconds.
    """

    def __init__(self):
        now = datetime.now(timezone.utc)
        # Anchor at today's UTC midnight so business-day math is stable.
        self._anchor = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        self._tick += 1
        return self._anchor + timedelta(microseconds=self._tick)

    def advance_seconds(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._anchor = self._anchor + timedelta(seconds=seconds)
        self._tick = 0


class DataStore:
    """All entity tables + the logical clock + a re-entrant lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # id -> dict for every persisted entity.
        self.customers: dict[str, dict] = {}
        self.accounts: dict[str, dict] = {}
        self.kyc_submissions: dict[str, dict] = {}
        self.options_approvals: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.day_trades: dict[str, dict] = {}
        self.acat_transfers: dict[str, dict] = {}

    def now(self) -> datetime:
        return self.clock.now()


# Module-level singleton consumed by every blueprint.
store = DataStore()


def reset_store() -> None:
    """Reset all in-memory state. Used by the optional test-reset endpoint."""
    with store.lock:
        store.clock = _Clock()
        store.customers.clear()
        store.accounts.clear()
        store.kyc_submissions.clear()
        store.options_approvals.clear()
        store.orders.clear()
        store.day_trades.clear()
        store.acat_transfers.clear()
