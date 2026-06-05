"""In-memory data store. NO seeding — every dict starts empty on each boot.

Storage is pure Python dicts keyed by UUID id. Per-test-server isolation kills and
re-launches the server before each test, so a fresh process always begins empty.
"""
import threading
import uuid

import clock

# A coarse global lock makes each request's multi-entity cascade atomic and protects
# the shared dicts on the threaded Flask dev server.
LOCK = threading.RLock()

# Collections, keyed by id. Insertion order preserved (Python 3.7+ dicts) so
# created_at-ascending listing is just insertion order.
shelters = {}
kennels = {}
animals = {}
intake_records = {}
kennel_assignments = {}
medical_records = {}
microchips = {}
owner_claims = {}
adopter_accounts = {}
adoption_applications = {}
foster_homes = {}
foster_placements = {}
euthanasia_decisions = {}


def reset():
    """Clear all collections (used only for in-process test scaffolding, never at boot)."""
    for coll in (
        shelters, kennels, animals, intake_records, kennel_assignments,
        medical_records, microchips, owner_claims, adopter_accounts,
        adoption_applications, foster_homes, foster_placements,
        euthanasia_decisions,
    ):
        coll.clear()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, versioned=True):
    """Attach id/created_at (+ updated_at/version when versioned) to a new record."""
    record["id"] = new_id()
    record["created_at"] = clock.to_iso(clock.now())
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Bump updated_at + version on a mutation (derived recomputes count too)."""
    record["updated_at"] = clock.to_iso(clock.now())
    record["version"] = record.get("version", 1) + 1
    return record
