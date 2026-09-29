"""In-memory data store.

Every collection starts empty on a fresh process; nothing is seeded.
"""

import itertools
import uuid

import clock

_seq = itertools.count(1)

KINDS = (
    "affiliations",
    "conversion_vendors",
    "practices",
    "doctors",
    "doctor_employments",
    "service_agreements",
    "service_line_items",
    "migration_batches",
    "payer_contracts",
    "fee_schedule_items",
    "payer_enrollments",
    "earnout_tranches",
    "supply_preference_exceptions",
    "vendor_consolidations",
    "clinical_quality_reviews",
)

store = {kind: {} for kind in KINDS}


def reset():
    global _seq
    _seq = itertools.count(1)
    for kind in KINDS:
        store[kind] = {}


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def insert(kind, fields, versioned=True):
    """Create a row with its system fields and register it in the store."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = clock.now()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    row["_kind"] = kind
    store[kind][row["id"]] = row
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return store[kind].get(row_id)


def all_rows(kind):
    return ordered(store[kind].values())


def ordered(rows):
    """Default ordering everywhere: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def find(kind, **filters):
    result = []
    for row in store[kind].values():
        if all(row.get(key) == value for key, value in filters.items()):
            result.append(row)
    return ordered(result)
