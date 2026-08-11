"""In-memory data store. Starts completely empty on every boot — no seeding."""
import itertools
import uuid

from clock import clock

_seq = itertools.count(1)

stores = {
    "regions": {},
    "corporate_accounts": {},
    "wellness_programs": {},
    "therapists": {},
    "therapist_licenses": {},
    "bookings": {},
    "chair_slots": {},
    "slot_claims": {},
    "travel_legs": {},
    "waivers": {},
    "invoices": {},
    "satisfaction_surveys": {},
    "payout_ledger_entries": {},
}


def new_id():
    return str(uuid.uuid4())


def insert(coll, entity):
    entity["_seq"] = next(_seq)
    stores[coll][entity["id"]] = entity
    return entity


def get(coll, eid):
    if eid is None:
        return None
    return stores[coll].get(eid)


def all_sorted(coll):
    return sorted(stores[coll].values(), key=lambda e: (e["created_at"], e["_seq"]))


def stamp_new(entity, with_version=True):
    """Populate common system fields at creation time."""
    entity["created_at"] = clock.iso()
    if with_version:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and increment version on any mutation."""
    entity["updated_at"] = clock.iso()
    entity["version"] = entity.get("version", 0) + 1


def public(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}
