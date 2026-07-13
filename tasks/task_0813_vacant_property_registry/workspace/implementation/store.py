"""In-memory data store and the server-controlled logical clock.

The store is intentionally empty on every boot. No entity is ever seeded,
preloaded, or hardcoded here; tests build all state through the API surface.
"""
import uuid

from util import parse_iso

# Server-startup default logical clock reading (never falls back to wall clock).
_CLOCK_DEFAULT = parse_iso("2026-03-01T00:00:00Z")


class Store:
    def __init__(self):
        self.clock = _CLOCK_DEFAULT
        self._seq = 0
        # One dict per entity kind, keyed by id (insertion-ordered).
        self.registrants = {}
        self.properties = {}
        self.maintenance_standards = {}
        self.inspections = {}
        self.violations = {}
        self.fines = {}
        self.liens = {}
        self.abatement_orders = {}
        self.receivership_referrals = {}
        self.demolition_listings = {}
        self.ledger_entries = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


# Single process-wide store instance (fresh per boot).
db = Store()
