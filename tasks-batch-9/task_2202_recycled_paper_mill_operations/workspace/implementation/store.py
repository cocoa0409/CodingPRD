"""In-memory data store. Starts EMPTY on every boot — no seeding, ever."""
import itertools
import uuid

import clock

# Entity kinds that carry only id + created_at (PRD §2.4)
LIGHT_ENTITIES = {"fiber_grades", "market_index_quotes", "paper_grade_specs", "reject_streams"}

COLLECTIONS = [
    "customers",
    "suppliers",
    "fiber_grades",
    "market_index_quotes",
    "fiber_purchase_orders",
    "fiber_receipts",
    "fiber_inventory_lots",
    "pulp_batches",
    "reject_streams",
    "paper_machines",
    "paper_grade_specs",
    "customer_orders",
    "production_runs",
    "grade_changes",
    "roll_sets",
    "effluent_permits",
    "effluent_readings",
    "sludge_manifests",
    "steam_allocations",
]

db = {c: {} for c in COLLECTIONS}
_seq = itertools.count(1)


def reset():
    global _seq
    for c in COLLECTIONS:
        db[c] = {}
    _seq = itertools.count(1)
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def insert(collection, row):
    """Assign id, created_at (+ updated_at/version for full entities), persist."""
    row["id"] = new_id()
    row["created_at"] = clock.now_iso()
    row["_seq"] = next(_seq)
    if collection not in LIGHT_ENTITIES:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    db[collection][row["id"]] = row
    return row


def touch(collection, row):
    """Refresh updated_at and bump version (PRD §2.4)."""
    if collection not in LIGHT_ENTITIES:
        row["updated_at"] = clock.now_iso()
        row["version"] = int(row.get("version", 1)) + 1
    return row


def get(collection, rid):
    if not isinstance(rid, str):
        return None
    return db[collection].get(rid)


def all_rows(collection):
    return sorted(db[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))
