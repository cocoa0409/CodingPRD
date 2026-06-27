"""In-memory data store. All state lives in process memory keyed by id.

Nothing is seeded or preloaded at startup; the store starts empty on every boot.
A fresh process (start.sh re-invocation) wipes every byte of state.
"""

import uuid
import itertools

from clock import Clock


class DB:
    def __init__(self):
        self.clock = Clock()
        # one dict per entity, keyed by id
        self.customers = {}
        self.units = {}
        self.agreements = {}
        self.payment_records = {}
        self.layaway_plans = {}
        self.layaway_payments = {}
        self.repair_tickets = {}
        self.consignment_listings = {}
        self.trade_ins = {}
        self.financing_applications = {}
        self.special_orders = {}
        self.lesson_enrollments = {}
        # monotonic sequence to provide a stable tiebreaker for equal timestamps
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def stamp(self):
        return self.clock.stamp()


# Single global store instance. Created fresh on every process start.
db = DB()
