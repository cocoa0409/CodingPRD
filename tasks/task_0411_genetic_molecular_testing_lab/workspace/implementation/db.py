"""In-memory data store. Wiped on every process boot (start.sh re-invocation).

No business entities are seeded here. The only initialized value is the
deterministic LabClock singleton, which the PRD (Section 2.4) requires to start
at 2026-01-01T00:00:00.000Z on first boot.
"""
import threading
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_now_from_clock(clock_value):
    return clock_value


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # LabClock singleton (Section 2.4). Not a common-fields resource.
        self.clock = {"current_utc": "2026-01-01T00:00:00.000Z"}

        # Entity collections, keyed by id. All start empty (no seeding).
        self.genes = {}
        self.panels = {}
        self.panel_genes = {}
        self.providers = {}
        self.test_orders = {}
        self.requisitions = {}
        self.consents = {}
        self.specimens = {}
        self.variants = {}
        self.reports = {}
        self.billings = {}
        self.sequencers = {}
        self.sequencer_runs = {}
        self.counselors = {}
        self.referrals = {}

    def now(self):
        """Current lab clock value (ISO string)."""
        return self.clock["current_utc"]

    def stamp_common(self, entity):
        """Apply common system fields on creation (Section 2.4)."""
        now = self.now()
        entity.setdefault("id", new_id())
        entity["created_at"] = now
        entity["updated_at"] = now
        entity["version"] = 1
        return entity

    def touch(self, entity):
        """Refresh updated_at and bump version on mutation (Section 2.4 / 2.5)."""
        entity["updated_at"] = self.now()
        entity["version"] = entity.get("version", 1) + 1
        return entity


store = Store()
