"""In-memory data store.

The store starts EMPTY on every boot. No seeding. Every entity is created via
the declared API surface. Each entity type lives in its own dict keyed by id.

Common audit fields (PRD §2.4): created_at, updated_at, version. BillingCharge is
the exception: only id + created_at.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Monotonic counter to give entities a stable created_at ordering even when two
# are created within the same millisecond. The PRD sorts lists by created_at ASC;
# this sequence is the deterministic tiebreak (insertion order).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


class Store:
    def __init__(self):
        self.clients = {}
        self.skus = {}
        self.bins = {}
        self.inventory_lots = {}
        self.receipts = {}
        self.orders = {}
        self.waves = {}
        self.pick_tasks = {}
        self.cartons = {}
        self.shipments = {}
        self.returns = {}
        self.cycle_counts = {}
        self.billing_charges = {}


# Singleton store. Recreated fresh on each process boot (module import).
store = Store()


def stamp_create(record):
    """Attach common audit fields for a freshly created entity (non-charge)."""
    record["created_at"] = now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_create_charge(record):
    """BillingCharge: id + created_at only (PRD §2.4)."""
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump version and refresh updated_at on a mutation that changed the record."""
    if "version" in record:
        record["version"] += 1
        record["updated_at"] = now_iso()
