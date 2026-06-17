"""In-memory data store. Empty on every boot — NO seeding, NO preload.

Each entity type is a dict keyed by id (UUID string). A monotonically
increasing sequence number is recorded per record so that created_at ties
(records minted within the same millisecond) can be broken deterministically
by insertion order for sorting/FIFO purposes.
"""
import itertools
import threading
import uuid

from response import now_iso

_lock = threading.RLock()
_seq = itertools.count(1)


class Store:
    def __init__(self):
        self.rfqs = {}
        self.part_lines = {}
        self.quotes = {}
        self.routing_ops = {}
        self.work_orders = {}
        self.material_lots = {}
        self.lot_allocations = {}
        self.machine_slots = {}
        self.inspections = {}
        self.inspection_stations = {}
        self.shipments = {}
        self.invoices = {}


db = Store()


def lock():
    return _lock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_fields(with_version=True):
    """Common system-managed quartet (PRD §2.5).

    InspectionStation passes with_version=False -> only id + created_at.
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (PRD §2.5/§2.6)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
