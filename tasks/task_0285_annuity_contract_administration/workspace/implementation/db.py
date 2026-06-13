"""In-memory data store.

Every collection is a plain dict keyed by the resource's UUID `id`. The store
holds NO seed data — it is empty on every process boot, which is required
because the test harness re-launches the server before every test.

An insertion sequence counter is maintained per collection so that list
ordering and chronological replay can break created_at ties by insertion order
(PRD §2.3, §3.5) without ever relying on the resource id.
"""

import itertools
import uuid

from clock import Clock


class Store:
    def __init__(self):
        self.products = {}
        self.contracts = {}
        self.premiums = {}
        self.sub_account_allocations = {}
        self.index_segments = {}
        self.crediting_events = {}
        self.withdrawals = {}
        self.beneficiaries = {}
        self.annuitizations = {}
        self.death_claims = {}
        self.exchanges = {}

        self.clock = Clock()

        # Monotonic insertion sequence — global, used to break created_at ties
        # deterministically by insertion order (never by id).
        self._seq = itertools.count(1)
        # Monotonic crediting-period counter for CreditingEvent.posted_period_index.
        self._crediting_period = itertools.count(0)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def next_crediting_period(self):
        return next(self._crediting_period)


# The single process-wide store. Re-created fresh on every import (every boot).
store = Store()
