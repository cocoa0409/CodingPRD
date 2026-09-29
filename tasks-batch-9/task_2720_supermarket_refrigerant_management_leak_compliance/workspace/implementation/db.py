"""In-memory data store and logical clock.

Storage is process-local Python dictionaries keyed by entity id. Nothing is
persisted, nothing is cached on disk, and the store is EMPTY on every boot --
tests build all of their preconditions through the declared endpoints.
"""
import itertools

import util
from errors import ApiError

COLLECTIONS = (
    "stores",
    "refrigerant_types",
    "systems",
    "technicians",
    "recovery_equipment",
    "cylinders",
    "service_records",
    "leak_events",
    "repair_attempts",
    "verification_tests",
    "extension_requests",
    "retrofit_plans",
    "regulatory_reports",
    "inspections",
)

# PRD 2.4: the logical clock starts at exactly this instant on every boot.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

NOT_FOUND = {
    "stores": "ERR_STORE_NOT_FOUND",
    "refrigerant_types": "ERR_REFRIGERANT_TYPE_NOT_FOUND",
    "systems": "ERR_SYSTEM_NOT_FOUND",
    "technicians": "ERR_TECHNICIAN_NOT_FOUND",
    "recovery_equipment": "ERR_RECOVERY_EQUIPMENT_NOT_FOUND",
    "cylinders": "ERR_CYLINDER_NOT_FOUND",
    "service_records": "ERR_SERVICE_RECORD_NOT_FOUND",
    "leak_events": "ERR_LEAK_EVENT_NOT_FOUND",
    "repair_attempts": "ERR_REPAIR_ATTEMPT_NOT_FOUND",
    "verification_tests": "ERR_VERIFICATION_TEST_NOT_FOUND",
    "extension_requests": "ERR_EXTENSION_REQUEST_NOT_FOUND",
    "retrofit_plans": "ERR_RETROFIT_PLAN_NOT_FOUND",
    "regulatory_reports": "ERR_REGULATORY_REPORT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
}


class Database(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = util.parse_instant(CLOCK_EPOCH)
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        return self.clock


db = Database()


def now():
    return db.clock


def collection(name):
    return getattr(db, name)


def values(name):
    return list(getattr(db, name).values())


def get(name, entity_id):
    """Resolve an id, or None. Non-string ids never resolve."""
    if not isinstance(entity_id, str):
        return None
    return getattr(db, name).get(entity_id)


def require(name, entity_id):
    found = get(name, entity_id)
    if found is None:
        raise ApiError(NOT_FOUND[name])
    return found


def insert(name, entity):
    getattr(db, name)[entity["id"]] = entity
    return entity


def new_entity(versioned=True):
    """Allocate the common system fields of PRD 2.5."""
    entity = {
        "id": util.new_id(),
        "_seq": db.next_seq(),
    }
    entity["created_at"] = db.clock
    if versioned:
        entity["updated_at"] = db.clock
        entity["version"] = 1
    return entity


def snapshot(entity):
    """Capture every field except the mutation markers themselves."""
    return {k: v for k, v in entity.items() if k not in ("updated_at", "version", "_seq")}


def commit(entity, snap):
    """Bump version/updated_at only when the resource actually changed.

    PRD 2.5: version increases by exactly 1 on every mutation of a resource
    and updated_at is refreshed to the logical clock on every such mutation.
    """
    if "version" not in entity:
        return False
    if snapshot(entity) != snap:
        entity["version"] += 1
        entity["updated_at"] = db.clock
        return True
    return False


def touch(entity):
    """Unconditional mutation marker bump (PRD 2.9 cascade on systems)."""
    entity["version"] += 1
    entity["updated_at"] = db.clock
