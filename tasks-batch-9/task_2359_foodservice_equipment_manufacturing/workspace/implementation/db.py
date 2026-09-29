"""In-memory store (PRD Section 2.4, 2.5). Empty on every boot — nothing is seeded."""
import itertools
import uuid
from datetime import datetime, timezone

from flask import g

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

STORE_NAMES = (
    "equipment_models",
    "certification_listings",
    "chain_accounts",
    "chain_configurations",
    "performance_validations",
    "construction_programs",
    "site_orders",
    "build_lines",
    "production_slots",
    "connected_units",
    "firmware_campaigns",
    "service_partners",
    "technician_certifications",
    "warranty_claims",
)


class Database(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK_UTC
        for name in STORE_NAMES:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Database()


def now():
    """The server-held logical clock — never wall time (PRD Section 2.5)."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def insert(store, fields):
    entity = {"id": new_id()}
    entity.update(fields)
    entity["created_at"] = db.clock
    entity["updated_at"] = db.clock
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    store[entity["id"]] = entity
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at and increment version once per request."""
    entity["updated_at"] = db.clock
    try:
        touched = g.setdefault("_touched_entities", set())
    except RuntimeError:  # outside an application context
        entity["version"] += 1
        return entity
    key = entity.get("id")
    if key not in touched:
        touched.add(key)
        entity["version"] += 1
    return entity


def ordered(collection):
    """Default ordering: created_at ascending, insertion order as the tie-break."""
    items = list(collection.values()) if isinstance(collection, dict) else list(collection)
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def children_of(store, field, parent_id):
    return [e for e in ordered(store) if e.get(field) == parent_id]
