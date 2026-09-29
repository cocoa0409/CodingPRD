"""In-memory data store and the logical assessment clock (PRD 2.5).

Storage is process-local Python dictionaries keyed by id. Nothing is persisted
and — deliberately — nothing is seeded: every collection below starts empty on
every boot and is populated exclusively through the public API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g


DEFAULT_LOGICAL_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Every collection is a plain dict keyed by the entity's UUID."""

    def __init__(self):
        self.districts = {}
        self.schools = {}
        self.windows = {}
        self.proctors = {}
        self.affidavits = {}
        self.sessions = {}
        self.registrations = {}
        self.lots = {}
        self.custody_events = {}
        self.reports = {}
        self.appeals = {}
        self.logical_clock = DEFAULT_LOGICAL_CLOCK_UTC
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def now():
    """The logical assessment clock; never falls back to wall-clock time."""
    return db.logical_clock


def set_clock(moment):
    db.logical_clock = moment


# --------------------------------------------------------------------------
# Common resource properties (PRD 2.4)
# --------------------------------------------------------------------------
def _touched_set():
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def create(collection, payload, common_fields=True):
    """Insert a new entity. ``common_fields`` is False only for CustodyEvent,
    which carries id and created_at but neither updated_at nor version."""
    entity = dict(payload)
    entity["id"] = new_id()
    stamp = now()
    entity["created_at"] = stamp
    if common_fields:
        entity["updated_at"] = stamp
        entity["version"] = 1
    entity["_seq"] = db.next_seq()
    collection[entity["id"]] = entity
    _touched_set().add(entity["id"])
    return entity


def touch(entity):
    """Refresh updated_at and increment version — once per request per resource.

    A single request that mutates the same resource through several hops of one
    cascade counts as one mutation (see the section 1.2 side-effect lists, which
    always say "increments <Entity>.version by 1").
    """
    if entity is None:
        return entity
    touched = _touched_set()
    entity["updated_at"] = now()
    if entity["id"] in touched:
        return entity
    touched.add(entity["id"])
    entity["version"] = entity.get("version", 1) + 1
    return entity


def sort_key(entity):
    """Default list ordering: creation timestamp ascending, insertion order as a
    deterministic tie-break."""
    return (entity["created_at"], entity["_seq"])


def ordered(values):
    return sorted(values, key=sort_key)
