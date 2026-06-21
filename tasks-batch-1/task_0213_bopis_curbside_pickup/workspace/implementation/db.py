"""In-memory data store. Empty on every boot — NO seeding, ever.

Every collection is a plain dict keyed by the entity's UUID id. A logical clock
lives here too. start.sh re-invocation creates a fresh process, wiping all state.
"""

import uuid
import threading

from clock import LogicalClock, now_iso


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = LogicalClock()
        self.customers = {}
        self.stores = {}
        self.products = {}
        self.store_inventory = {}
        self.pickup_slots = {}
        self.orders = {}
        self.order_lines = {}
        self.substitutions = {}
        self.holds = {}
        self.curbside_checkins = {}
        self.pickup_events = {}
        self.inventory_movements = {}
        # monotonic sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def stamp_common(rec):
    """Attach common system fields: id, created_at, updated_at, version."""
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def stamp_ledger(rec):
    """Lightweight ledger rows carry only id + created_at (PRD §2.4)."""
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
