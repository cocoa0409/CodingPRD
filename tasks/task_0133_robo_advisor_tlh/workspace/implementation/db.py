"""In-memory data store + logical clock — see PRD §2.9 / §3.12."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """Server-side logical clock.

    Advanced exclusively via POST /_clock/advance. now() returns a
    strictly monotonic timestamp anchored at the current logical
    instant so that created_at / updated_at remain orderable while
    the calendar date is fully controlled by the test harness.
    """

    def __init__(self):
        # Anchor at "now" on process start so timestamps look natural;
        # tests should call /_clock/advance to position the clock.
        now = datetime.now(timezone.utc)
        # Round to milliseconds to keep ISO output stable.
        anchor = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        self._logical = anchor
        self._tick = 0

    def now(self) -> datetime:
        # Increment a microsecond tick so every now() is strictly
        # later than the last (and later than wall-time anchor).
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def advance_to(self, target: datetime) -> None:
        """Set the logical clock to `target` (UTC-aware datetime).

        Per PRD §3.12: 'sets the logical clock to the instant
        supplied as an optional to_iso body parameter'. The semantic
        is absolute set — tests may move the clock to any instant,
        including instants earlier than the current logical clock,
        to drive the time-based workflows (wash-sale window,
        quarter rollover, 30-day post-issue void window) deterministically.
        """
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        target = target.astimezone(timezone.utc)
        self._logical = target
        self._tick = 0

    def advance_tick(self) -> None:
        """When to_iso is omitted, advance by one tick."""
        self._tick += 1


class DataStore:
    """All entities held in memory keyed by id, plus the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Entity tables: id -> dict
        self.clients = {}
        self.advisors = {}  # entity-backed identity for Advisor role; opaquely seeded via headers (see middleware).
        self.risk_questionnaires = {}
        self.model_portfolios = {}
        self.accounts = {}
        self.securities = {}
        self.correlation_links = {}
        self.positions = {}
        self.lots = {}
        self.trades = {}
        self.wash_sale_events = {}
        self.harvest_opportunities = {}
        self.rebalance_runs = {}
        self.dividend_events = {}
        self.forms_1099b = {}

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used throughout the app.
store = DataStore()
