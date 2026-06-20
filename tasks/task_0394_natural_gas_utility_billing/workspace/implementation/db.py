"""In-memory data store for the Natural Gas Utility Billing API.

All state is held in plain Python dicts keyed by id. Nothing is persisted;
the store is reconstructed empty on every process boot. NO entity data is
seeded — tests build all state via the API surface.

The only pre-existing record is the singleton Clock, whose default values come
from PRD §2.8 / SCAFFOLD §1.1 (current_utc = 2026-01-01T00:00:00.000Z,
heating_season_active = false). The Clock is system configuration, not an
entity-under-test; it carries no id and is not seeded with any account data.
"""

import threading
import uuid


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.rate_schedules = {}
        self.pga_schedules = {}
        self.accounts = {}
        self.meters = {}
        self.meter_reads = {}
        self.bills = {}
        self.budget_plans = {}
        self.payments = {}
        self.service_orders = {}
        self.tickets = {}
        self.deposits = {}
        self.low_income_credits = {}

        # Monotonic creation sequence for stable created_at tie-breaking and
        # default ordering (PRD §2.3: list results ordered by created_at ASC).
        self._seq = 0

        # Singleton logical clock (PRD §2.8).
        self.clock = {
            "current_utc": "2026-01-01T00:00:00.000Z",
            "heating_season_active": False,
        }

        self.lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


# Module-level singleton store. Constructed fresh on import (process boot).
store = Store()
