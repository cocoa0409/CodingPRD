"""In-memory data store.

Storage is Python dicts keyed by id and nothing else. The store starts empty on
every boot: no entity is ever seeded, preloaded or hardcoded here. Every row is
created by an API call.
"""

from core import clock, new_id

# One dict per collection, keyed by the record's server-minted id.
jurisdictions = {}
plan_cycles = {}
hazard_profiles = {}
assets = {}
assessments = {}
projects = {}
links = {}
analyses = {}
programs = {}
sessions = {}
endorsements = {}
pacts = {}
commitments = {}

COLLECTIONS = {
    "jurisdictions": jurisdictions,
    "plan_cycles": plan_cycles,
    "hazard_profiles": hazard_profiles,
    "assets": assets,
    "assessments": assessments,
    "projects": projects,
    "links": links,
    "analyses": analyses,
    "programs": programs,
    "sessions": sessions,
    "endorsements": endorsements,
    "pacts": pacts,
    "commitments": commitments,
}

# Monotonic insertion counter. created_at comes from a logical clock that does
# not advance on its own, so rows routinely share a created_at; _seq keeps the
# "sorted by created_at ascending" page walk of PRD 2.3 stable and deterministic.
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def insert(collection, record, common_fields=True, versioned=True):
    """Insert a fresh record, stamping id, created_at and (usually) version."""
    record["id"] = new_id()
    record["created_at"] = clock.now()
    if common_fields:
        if versioned:
            record["updated_at"] = clock.now()
            record["version"] = 1
    record["_seq"] = _next_seq()
    collection[record["id"]] = record
    return record


def touch(record):
    """A mutation that changes the record: refresh updated_at, bump version."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
    return record


def ordered(collection):
    """Every collection is returned sorted by created_at ascending."""
    return sorted(collection.values(), key=lambda row: (row["created_at"], row["_seq"]))


def reset():
    for coll in COLLECTIONS.values():
        coll.clear()
    global _seq
    _seq = 0
    clock.reset()
