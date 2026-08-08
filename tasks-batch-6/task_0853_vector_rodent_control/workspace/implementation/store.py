"""In-memory data store. Starts EMPTY on every boot -- nothing is seeded."""

import itertools
import uuid

import lclock

zones = {}
owners = {}
properties = {}
officers = {}
complaints = {}
inspections = {}
assessments = {}
orders = {}
notices = {}
stations = {}
readings = {}
invoices = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    """Attach the common creation fields (PRD 2.4)."""
    ts = lclock.now()
    record["id"] = new_id()
    record["created_at"] = ts
    record["_seq"] = next(_seq)
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at on any mutation (PRD 2.4)."""
    if "updated_at" in record:
        record["updated_at"] = lclock.now()
    return record


def bump(record):
    """Refresh updated_at and increment version by exactly one."""
    record["updated_at"] = lclock.now()
    record["version"] = record.get("version", 1) + 1
    return record


def ordered(collection, predicate=None):
    """Rows ordered by created_at ascending (PRD 2.3), stable on insertion."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
