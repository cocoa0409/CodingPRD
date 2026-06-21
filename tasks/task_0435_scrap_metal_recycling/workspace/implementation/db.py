"""In-memory data store. Everything is wiped on process restart by design.

NO seeding, NO preloading. Tests build all state via the declared API surface.
"""
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.sellers = {}
        self.commodity_prices = {}
        self.tickets = {}
        self.line_items = {}
        self.payouts = {}
        self.containers = {}
        self.mill_shipments = {}
        self.hedges = {}
        self.theft_reports = {}
        # Monotonic insertion counter to enforce created_at-ascending ordering
        # deterministically even when timestamps collide at millisecond precision.
        self._seq = 0
        self._lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def stamp_create(record):
    """Attach common create fields for a mutable resource (PRD §2.4)."""
    ts = now_iso()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_create_append_only(record):
    """Common create fields for an append-only resource (TicketLineItem):
    only id + created_at, no updated_at / version (PRD §2.4)."""
    record["id"] = db.new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutate bookkeeping: refresh updated_at and bump version by 1 (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


# Fields that are internal bookkeeping and must never be serialized to clients.
_HIDDEN_FIELDS = {"_seq"}


def public(record):
    """Return a copy of a record without internal-only fields."""
    return {k: v for k, v in record.items() if k not in _HIDDEN_FIELDS}
