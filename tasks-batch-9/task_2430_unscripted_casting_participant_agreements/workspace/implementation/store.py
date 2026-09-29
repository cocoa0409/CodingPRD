"""In-memory data store.

Every collection starts EMPTY on every boot.  No entity is ever seeded,
preloaded or hardcoded: tests build all preconditions through the declared
API surface.
"""

import itertools
import threading
import uuid

from flask import g

from clock import clock

_seq_counter = itertools.count(1)
_seq_lock = threading.Lock()

# Collections keyed by id.
productions = {}
locations = {}
casting_calls = {}
applicants = {}
screening_items = {}
minor_protections = {}
agreements = {}
negotiation_rounds = {}
welfare_protocols = {}
shoot_blocks = {}
releases = {}
post_obligations = {}
complaints = {}

write_lock = threading.RLock()

APPEND_ONLY = {"negotiation_round", "release"}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    with _seq_lock:
        return next(_seq_counter)


def new_record(kind, fields, versioned=True):
    """Build a record with the common audit fields of PRD §2.4."""
    now = clock.now_iso()
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = now
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    record["_kind"] = kind
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version — once per record per request."""
    if record is None or "version" not in record:
        return record
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if record["id"] in touched:
        return record
    touched.add(record["id"])
    record["updated_at"] = clock.now_iso()
    record["version"] = record["version"] + 1
    return record


def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_all(records):
    return [serialize(r) for r in records]


def by_seq(records):
    """Default list ordering: created_at ascending (insertion order)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
