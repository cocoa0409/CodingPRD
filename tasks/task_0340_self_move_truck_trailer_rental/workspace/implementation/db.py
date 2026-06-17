"""In-memory data store. Starts empty on every boot — NO seeding."""
import threading
import uuid

from response import now_iso

# A global lock for serializing writes (simple, correct for this benchmark).
LOCK = threading.RLock()


class Store:
    """A keyed collection for one entity type, plus an insertion sequence so
    creation order (and created_at-ascending sort) is stable even when two rows
    share an identical created_at timestamp."""

    def __init__(self, versioned=True):
        self.items = {}  # id -> dict
        self.versioned = versioned
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def all(self):
        # Sorted by creation order (created_at ascending, stable on _seq).
        return sorted(self.items.values(), key=lambda r: r["_seq"])

    def get(self, rid):
        return self.items.get(rid)

    def put(self, row):
        self.items[row["id"]] = row

    def delete(self, rid):
        self.items.pop(rid, None)


# Entity collections. Two append-only event types (damage_reports, ledger)
# carry only id + created_at (no version/updated_at).
locations = Store()
equipment_classes = Store()
coverage_plans = Store()
supplies = Store()
customers = Store()
reservations = Store()
addons = Store()
supply_lines = Store()
equipment = Store()
contracts = Store()
damage_reports = Store(versioned=False)
transfers = Store()
ledger = Store(versioned=False)


def new_id():
    return str(uuid.uuid4())


def make_common(store, versioned=True):
    """Build the common system fields for a new record."""
    ts = now_iso()
    base = {
        "id": new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if versioned:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(row):
    """Advance updated_at and bump version on a mutation."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] += 1
