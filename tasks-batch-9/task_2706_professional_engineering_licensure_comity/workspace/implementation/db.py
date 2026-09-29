"""In-memory data store.

Everything lives in module level dicts.  Nothing is persisted and nothing is
seeded: a fresh process starts with an entirely empty board.
"""
from datetime import datetime

from util import UTC, new_uuid

# The logical board clock starts exactly at 2026-08-01T00:00:00Z on every boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "engineers",
    "licenses",
    "applications",
    "experience_records",
    "references",
    "test_centers",
    "exam_authorizations",
    "exam_appointments",
    "firm_registrations",
    "plan_submissions",
    "cpc_reports",
    "pdh_records",
    "cpc_audits",
    "cases",
    "consent_orders",
)

store = {name: {} for name in COLLECTIONS}

state = {
    "clock": CLOCK_EPOCH,
    "license_seq": 0,
    "row_seq": 0,
}


def reset():
    for name in COLLECTIONS:
        store[name] = {}
    state["clock"] = CLOCK_EPOCH
    state["license_seq"] = 0
    state["row_seq"] = 0


def clock():
    return state["clock"]


def set_clock(value):
    state["clock"] = value


def next_license_number():
    state["license_seq"] += 1
    return "PE-%06d" % state["license_seq"]


def _next_seq():
    state["row_seq"] += 1
    return state["row_seq"]


def insert(collection, row, *, versioned=True):
    """Stamp system fields and persist the row."""
    now = clock()
    row["id"] = row.get("id") or new_uuid()
    row["created_at"] = now
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = _next_seq()
    store[collection][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock()
    return row


def write(row, **changes):
    """Apply changes; bump the row exactly once when anything actually moved."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return store[collection].get(row_id)


def all_rows(collection):
    """Every row in default order: created_at ascending (insertion order)."""
    return sorted(store[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))
