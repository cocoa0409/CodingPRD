"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding, no preloaded entities.
All entities are created exclusively via the API surface.
"""
import uuid
from datetime import datetime, timezone

# Logical clock: starts at exactly 2026-08-01T00:00:00Z. Never wall-clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

STORE = {
    "venues": {},
    "suites": {},
    "seasons": {},
    "events": {},
    "accounts": {},
    "agreements": {},
    "invoices": {},
    "payments": {},
    "catering_orders": {},
    "credentials": {},
    "rentals": {},
    "transfers": {},
    "renewal_offers": {},
    "waitlist_entries": {},
    "assessments": {},
}

_CLOCK = {"now": DEFAULT_CLOCK}
_SEQ = {"n": 0}


def clock():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def mint_id():
    return str(uuid.uuid4())


def new_entity(fields):
    """Create the common system fields for a fresh entity."""
    now = clock()
    ent = dict(fields)
    ent["id"] = mint_id()
    ent["created_at"] = now
    ent["updated_at"] = now
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    """Register a mutation: bump optimistic-concurrency version and updated_at."""
    ent["version"] = int(ent.get("version", 1)) + 1
    ent["updated_at"] = clock()


def insert(coll, ent):
    STORE[coll][ent["id"]] = ent
    return ent


def get(coll, eid):
    return STORE[coll].get(eid)


def all_of(coll):
    return STORE[coll].values()


def find(coll, pred):
    return [e for e in STORE[coll].values() if pred(e)]
