"""In-memory data store. No persistence, no seeding — starts empty on every boot.

Every entity is a plain dict keyed by its UUID id. A monotonically increasing
sequence guarantees a unique, strictly-ordered created_at tiebreaker even when
many rows are stamped at the same logical clock instant (PRD §3.8 walks charges
in created_at ascending order; we preserve insertion order as the tiebreaker).
"""
import uuid

from clock import Clock, fmt_iso


class DB:
    def __init__(self):
        self.clock = Clock()
        # one dict per entity type, keyed by id
        self.container_models = {}
        self.protection_plans = {}
        self.depots = {}
        self.depot_inventory = {}
        self.customers = {}
        self.rental_agreements = {}
        self.container_units = {}
        self.crews = {}
        self.trucks = {}
        self.delivery_jobs = {}
        self.move_orders = {}
        self.access_visits = {}
        self.packing_supply_orders = {}
        self.charges = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        return self.clock.now()

    def now_iso(self):
        return fmt_iso(self.clock.now())


# Module-level singleton store. Fresh on every process boot.
db = DB()
