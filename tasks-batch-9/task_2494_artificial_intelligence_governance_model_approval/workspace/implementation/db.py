"""In-memory data store.

Every collection is a plain dict keyed by the record's server-generated `id`.
Nothing is seeded, preloaded or hardcoded: the store starts empty on every boot
and all state is created by clients through the declared endpoints.
"""
import uuid

import clock

# --- collections -----------------------------------------------------------
use_cases = {}
classification_snapshots = {}
review_gates = {}
model_assets = {}
model_bindings = {}
vendor_assessments = {}
test_evaluations = {}
oversight_designs = {}
disclosure_notices = {}
monitoring_incidents = {}
shadow_deployments = {}
ledger_entries = {}

_COLLECTIONS = (
    use_cases,
    classification_snapshots,
    review_gates,
    model_assets,
    model_bindings,
    vendor_assessments,
    test_evaluations,
    oversight_designs,
    disclosure_notices,
    monitoring_incidents,
    shadow_deployments,
    ledger_entries,
)

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def insert(collection, record):
    """Assign the identity fields shared by every record and store it."""
    record["id"] = new_id()
    record["created_at"] = clock.now()
    record["_seq"] = next_seq()
    collection[record["id"]] = record
    return record


def touch(record):
    """A row was mutated: refresh updated_at and bump version by exactly 1."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 0) + 1
    return record


def ordered(records):
    """Default list ordering: created_at ascending, insertion order for ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(collection):
    return ordered(collection.values())


def reset():
    for collection in _COLLECTIONS:
        collection.clear()
    global _seq
    _seq = 0
