"""In-memory data store.

Storage is process-local dicts only. The store starts empty on every boot —
no seeding, no preloading, no hardcoded entities. Every entity a test needs
is built through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        self._last_ts = None
        # entity tables: id -> dict
        self.service_lines = {}
        self.cost_centers = {}
        self.physicians = {}
        self.drgs = {}
        self.cost_models = {}
        self.refreshes = {}
        self.cases = {}
        self.activity_lines = {}
        self.implants = {}
        self.supply_lines = {}
        self.payer_contracts = {}
        self.budget_periods = {}

    def next_seq(self):
        """Monotonic creation-order sequence (defines created_at ASC order)."""
        self.seq += 1
        return self.seq

    def now_iso(self):
        """ISO 8601 UTC timestamp with three fractional digits, strictly
        non-decreasing so created_at ordering is stable."""
        now = datetime.now(timezone.utc)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + timedelta(milliseconds=1)
        self._last_ts = now
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    """System-managed fields for primary resources (PRD §2.4)."""
    ts = store.now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Register a modification: bump version and refresh updated_at."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = store.now_iso()
