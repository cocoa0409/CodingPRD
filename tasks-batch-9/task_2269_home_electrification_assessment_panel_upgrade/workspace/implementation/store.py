"""In-memory data store.

Everything lives in plain dicts keyed by id. The store starts EMPTY on every
boot: no entity is seeded, preloaded or hardcoded anywhere.
"""
import itertools
import uuid

import clock

# --- collections ------------------------------------------------------------
programs = {}
catalog_items = {}
households = {}
income_verifications = {}
contractors = {}
inspectors = {}
assessments = {}
eligible_measures = {}
projects = {}
project_measures = {}
reservations = {}
stacking_declarations = {}
inspections = {}
clawback_actions = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_record(fields, versioned=True):
    """Create a record dict with the uniform audit fields.

    `versioned` records carry created_at, updated_at and version;
    append-only audit rows (Inspector, EligibleMeasure, ClawbackAction) carry
    only created_at.
    """
    stamp = clock.now_iso()
    record = {"id": new_id(), "created_at": stamp}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    record.update(fields)
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version by one."""
    if record is None:
        return record
    record["updated_at"] = clock.now_iso()
    if "version" in record:
        record["version"] = record["version"] + 1
    return record


def public(record):
    """Strip internal bookkeeping keys before serialisation."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ordered(collection, predicate=None):
    """All records of a collection in created_at ascending order."""
    values = [r for r in collection.values() if predicate is None or predicate(r)]
    values.sort(key=lambda r: r["_seq"])
    return values
