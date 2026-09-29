"""In-memory data store.

Every collection starts empty on boot.  Nothing is ever seeded, preloaded or
hardcoded: each record is created by an API call.
"""
import threading
import uuid

from flask import g, has_request_context

import clock

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.funds = {}
        self.share_classes = {}
        self.accounts = {}
        self.positions = {}
        self.nav_records = {}
        self.trades = {}
        self.distributions = {}
        self.payments = {}
        self.plans = {}
        self.registrations = {}
        self.cases = {}
        self.reconciliations = {}
        self.ledger_entries = {}


store = Store()


def new_id():
    return str(uuid.uuid4())


def _state():
    if not has_request_context():
        return None
    if not hasattr(g, "_db_dirty"):
        g._db_dirty = []
        g._db_created = set()
    return g


def create(collection, fields, versioned=True):
    """Insert a new record.  Creation counts as version 1 -- further mutations
    inside the same request do not bump it again."""
    record = dict(fields)
    record["id"] = new_id()
    stamp = clock.real_now_iso()
    record["created_at"] = stamp
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    collection[record["id"]] = record
    state = _state()
    if state is not None:
        state._db_created.add(record["id"])
    return record


def touch(record):
    """Mark a record mutated; the version bump is applied once per request."""
    state = _state()
    if state is None:
        bump_now(record)
        return
    if record["id"] in state._db_created:
        return
    if not any(r is record for r in state._db_dirty):
        state._db_dirty.append(record)


def bump_now(record):
    if "version" in record:
        record["version"] = record.get("version", 1) + 1
        record["updated_at"] = clock.real_now_iso()


def set_field(record, key, value):
    """Assign a derived field, marking the record dirty only when it changed."""
    old = record.get(key)
    changed = (old is None) != (value is None)
    if not changed and old is not None:
        changed = old != value
    record[key] = value
    if changed:
        touch(record)
    return changed


def flush():
    """Apply the deferred version/updated_at bumps.  Called before serialising."""
    state = _state()
    if state is None:
        return
    for record in state._db_dirty:
        if record["id"] in state._db_created:
            continue
        bump_now(record)
    state._db_dirty = []


def values(collection):
    return list(collection.values())
