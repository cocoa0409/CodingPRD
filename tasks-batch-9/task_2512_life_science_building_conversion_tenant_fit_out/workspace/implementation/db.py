"""In-memory data store.

Every collection starts EMPTY on every boot -- nothing is seeded, preloaded or
hardcoded. Tests build all preconditions through the declared API surface.
"""
import itertools
import uuid

import clock

_seq = itertools.count(1)

# Fourteen peer collections, keyed by id (PRD 2.5).
buildings = {}
floors = {}
assessments = {}
scope_items = {}
tenants = {}
leases = {}
proposals = {}
projects = {}
phases = {}
reservations = {}
permits = {}
amenities = {}
allocations = {}
records = {}


def new_id():
    return str(uuid.uuid4())


def create(collection, fields):
    """Mint a record with the four shared server-managed properties (PRD 2.4)."""
    moment = clock.now()
    record = {
        "id": new_id(),
        "created_at": moment,
        "updated_at": moment,
        "version": 1,
        "_seq": next(_seq),
    }
    record.update(fields)
    collection[record["id"]] = record
    return record


def touch(record):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4, 2.10)."""
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1
    return record


def ordered(records_iterable):
    """Default ordering: created_at ascending, stable by insertion (PRD 2.3)."""
    return sorted(records_iterable, key=lambda r: (r["created_at"], r["_seq"]))
