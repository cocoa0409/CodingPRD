"""In-memory data store and logical clock.

The store starts completely empty on every boot — every entity is created
through the declared API surface. The logical clock starts at the fixed
default 2026-08-01T00:00:00Z and is the single source of "now" for the
whole system (PRD section 2.4); it is only moved by POST /_clock/set_current_utc.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # Serializes every request so cascades and OCC checks are atomic.
        self.lock = threading.RLock()
        # Logical clock (aware datetime, UTC).
        self.clock = DEFAULT_CLOCK
        # Entity tables, keyed by id, insertion-ordered.
        self.properties = {}
        self.residents = {}
        self.technicians = {}
        self.vendors = {}
        self.parts = {}
        self.work_orders = {}
        self.work_order_parts = {}
        self.purchase_requests = {}
        self.chargebacks = {}


store = Store()


def new_record():
    """Common system-managed fields (PRD 2.5): UUID id, timestamps, version 1."""
    now = store.clock
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(rec):
    """Refresh updated_at and bump version by exactly one (PRD 2.5)."""
    rec["updated_at"] = store.clock
    rec["version"] += 1
