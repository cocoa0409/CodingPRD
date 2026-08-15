"""In-memory store + logical clock. The store starts EMPTY on every boot —
no seeding; every entity is constructed through the declared API surface."""

import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    "foundries": {},
    "customers": {},
    "patterns": {},
    "orders": {},
    "equipment": {},
    "heats": {},
    "pour_slots": {},
    "molds": {},
    "castings": {},
    "inspections": {},
    "scrap_records": {},
    "return_lots": {},
    "sand_batches": {},
    "claims": {},
}

_seq = itertools.count(1)

# Logical clock (PRD 2.4): startup default is exactly 2026-08-01T00:00:00Z;
# never falls back to wall-clock.
LOGICAL_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return LOGICAL_NOW


def set_logical_now(dt):
    global LOGICAL_NOW
    LOGICAL_NOW = dt.astimezone(timezone.utc).replace(microsecond=0)


def wall_now():
    return datetime.now(timezone.utc)


def new_record(collection, fields):
    now = wall_now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(_seq),
    }
    rec.update(fields)
    STORE[collection][rec["id"]] = rec
    return rec


def get(collection, rid):
    return STORE[collection].get(rid)


def all_of(collection):
    return STORE[collection].values()


def touch(rec):
    """PRD 2.5: updated_at refreshed and version incremented on every mutation."""
    rec["updated_at"] = wall_now()
    rec["version"] += 1
