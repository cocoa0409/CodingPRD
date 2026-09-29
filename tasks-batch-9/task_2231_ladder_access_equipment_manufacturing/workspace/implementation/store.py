"""In-memory data store and the deterministic logical clock.

The store starts completely EMPTY on every process boot. Nothing is seeded,
preloaded or hardcoded: every entity is built by callers through the declared
API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.4: the clock starts at 2026-08-01T00:00:00Z when the process starts and
# never advances on its own.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "products",
    "design_revisions",
    "product_documents",
    "test_benches",
    "bench_reservations",
    "test_campaigns",
    "load_tests",
    "production_lots",
    "joint_samples",
    "listing_bodies",
    "listing_records",
    "consumer_registrations",
    "field_incidents",
    "corrective_actions",
    "recall_events",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT


db = Store()
request_lock = threading.RLock()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------
def now():
    return db.clock


def set_clock(value):
    db.clock = value


# --------------------------------------------------------------------------
# id / common field helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _bucket(name):
    bucket = getattr(g, name, None)
    if bucket is None:
        bucket = []
        setattr(g, name, bucket)
    return bucket


def _contains(bucket, entity):
    for item in bucket:
        if item is entity:
            return True
    return False


def mark_dirty(entity):
    """Record that a pre-existing entity was mutated during this request.

    PRD 2.7/2.4: a mutated resource gets a refreshed updated_at and its version
    increments -- including server-initiated cascade mutations and derived-field
    recomputation. commit() applies that exactly once per entity per request.
    """
    if entity is None:
        return
    bucket = _bucket("_dirty_entities")
    if not _contains(bucket, entity):
        bucket.append(entity)


def register_new(entity):
    bucket = _bucket("_new_entities")
    if not _contains(bucket, entity):
        bucket.append(entity)
    return entity


def commit():
    if getattr(g, "_committed", False):
        return
    g._committed = True
    dirty = getattr(g, "_dirty_entities", None) or []
    fresh = getattr(g, "_new_entities", None) or []
    stamp = now()
    for entity in dirty:
        if _contains(fresh, entity):
            continue
        if "version" in entity:
            entity["version"] = entity["version"] + 1
        if "updated_at" in entity:
            entity["updated_at"] = stamp


def base_record(versioned=True):
    stamp = now()
    record = {"id": new_id(), "created_at": stamp}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    return record
