"""In-memory data store.

Storage is purely in-memory (Python dicts keyed by id). There is NO persistence
to disk and NO seeding of any entity at startup: every entity is created by tests
via the declared API surface. A fresh process (start.sh re-invocation) wipes all
state.
"""

import uuid

from clock import LogicalClock


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.clinics = {}
        self.petowners = {}
        self.coolers = {}
        self.retorts = {}
        self.batches = {}
        self.cases = {}
        self.transport_legs = {}
        self.custody_events = {}
        self.keepsake_orders = {}
        self.certificates = {}
        self.return_routes = {}
        self.memorial_addons = {}
        self.invoices = {}

        # Monotonic creation counter to provide a stable created_at tie-break
        # ordering (the logical clock can be frozen, so two entities may share
        # an identical created_at; _seq preserves true creation order).
        self._seq = 0

        # Sequential counters.
        self._certificate_number = 0

        # Logical clock (domain timestamps).
        self.clock = LogicalClock()

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_certificate_number(self):
        self._certificate_number += 1
        return str(self._certificate_number)


# Single global store instance, created once at import time. It is never
# populated with any records here.
store = Store()
