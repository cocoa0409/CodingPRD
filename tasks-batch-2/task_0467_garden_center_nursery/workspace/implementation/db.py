"""In-memory store. Wiped on every process boot — no seeding, no persistence."""
import threading
import uuid

from clock import clock, to_iso8601_millis


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.nurseries = {}
        self.accounts = {}
        self.products = {}
        self.inventory_lots = {}
        self.care_log_entries = {}
        self.promotions = {}
        self.vehicles = {}
        self.orders = {}
        self.order_lines = {}
        self.special_orders = {}
        self.deliveries = {}
        self.warranty_claims = {}
        self.loyalty_events = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return to_iso8601_millis(clock.get())


def base_versioned():
    """Common quartet: id, created_at, updated_at, version (PRD §2.5)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_ledger():
    """Append-only ledger record: id + created_at only (PRD §2.5)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD §2.6)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
