"""In-memory data store.

Every collection is a plain dict keyed by the server-minted UUID id. The store
starts EMPTY on every process boot — nothing is seeded, preloaded, or
hardcoded. The test harness restarts the server (via start.sh) before every
test, and re-import of this module recreates the empty dicts, guaranteeing a
fresh, isolated state per test.
"""

import uuid
import threading

from timeutil import now_iso
from clock import clock


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.patients = {}
        self.device_models = {}
        self.allowance_benefits = {}
        self.evaluations = {}
        self.orders = {}
        self.adjustments = {}
        self.warranty_claims = {}
        self.subscriptions = {}
        self.supply_cycles = {}
        self.recalls = {}
        self.ledger = {}

    # --- id / timestamp helpers ---------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def stamp_create(self, obj, with_version=True):
        """Populate the system fields on a freshly created entity.

        created_at/updated_at use the *logical clock* so that test-driven
        time advances are reflected in entity timestamps where relevant.
        """
        now = now_iso(clock.now())
        obj["id"] = self.new_id()
        obj["created_at"] = now
        if with_version:
            obj["updated_at"] = now
            obj["version"] = 1
        return obj

    def touch(self, obj):
        """Apply a mutation: refresh updated_at and bump version by 1.

        Used for direct mutations and for every cascaded side effect (PRD
        §2.5: each cascade hop is an independent mutation)."""
        obj["updated_at"] = now_iso(clock.now())
        obj["version"] = obj.get("version", 1) + 1
        return obj


db = DB()
