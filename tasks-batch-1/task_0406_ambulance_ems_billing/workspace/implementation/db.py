"""In-memory data store for the Ambulance EMS Billing API.

All state is held in plain Python dicts keyed by id. Nothing is persisted; the
store is reconstructed empty on every process boot. NO entity data is seeded —
tests build all state via the API surface.
"""

import threading
import uuid


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.agencies = {}
        self.agency_staff = {}
        self.payer_plans = {}
        self.patients = {}
        self.vehicles = {}
        self.crew_members = {}
        self.unit_assignments = {}
        self.transports = {}
        self.charges = {}
        self.claims = {}
        self.remittance_lines = {}
        self.payments = {}
        self.adjustments = {}

        # Monotonic creation sequence for stable created_at tie-breaking and
        # default ordering (PRD §2.3: list results ordered by created_at ASC).
        self._seq = 0

        self.lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


# Module-level singleton store. Constructed fresh on import (process boot).
store = Store()
