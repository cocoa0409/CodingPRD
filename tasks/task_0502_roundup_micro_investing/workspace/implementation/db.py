"""In-memory data store (PRD §2 — flat topology, one dict per entity collection).

Storage is process-memory only: plain Python dicts keyed by id. Nothing is
seeded at import time; every entity is created by an API call. A fresh process
(start.sh re-invocation under per-test-server isolation) wipes all state.
"""

import datetime
import uuid

# PRD §2.10 — On startup the logical clock reads exactly 2026-01-01T00:00:00Z.
_CLOCK_DEFAULT = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


class Store:
    def __init__(self):
        # One top-level collection per entity (flat topology, PRD §2).
        self.subscription_plans = {}
        self.model_portfolios = {}
        self.found_money_offers = {}
        self.accounts = {}
        self.linked_cards = {}
        self.roundup_accruals = {}
        self.recurring_contributions = {}
        self.buckets = {}
        self.orders = {}
        self.tax_lots = {}
        self.found_money_rewards = {}
        self.referrals = {}
        self.cash_transactions = {}

        # Monotonic creation sequence — default sort key (creation order ASC).
        self._seq = 0
        # Logical clock (PRD §2.10).
        self._clock = _CLOCK_DEFAULT

    # ---- identity / sequencing ----
    def new_id(self):
        # UUID with no type prefix (PRD §2.4).
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock (PRD §2.10) ----
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


# Single global store instance. Empty at construction — NO seeding.
store = Store()
