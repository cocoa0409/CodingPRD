"""In-memory data store and logical clock.

Storage is process-local and starts completely empty on every boot.
No entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.4: the logical clock begins at this fixed instant and never falls back
# to wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self.chapters = {}
        self.standards = {}
        self.owner_assignments = {}
        self.evidence_items = {}
        self.units = {}
        self.tracers = {}
        self.observations = {}
        self.rounding_sessions = {}
        self.tickets = {}
        self.windows = {}
        self.findings = {}
        self.submissions = {}
        self.pprs = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical clock instant."""
    return db.clock


def _touched_set():
    try:
        return g._touched
    except AttributeError:
        g._touched = set()
        return g._touched


def register_created(entity):
    """A resource created inside this request must not have its version bumped
    again by a cascade fired in the same request."""
    _touched_set().add(id(entity))


def touch(entity):
    """Record a mutation: refresh updated_at and bump version at most once per
    request per entity (PRD 2.5 / 2.9)."""
    if entity is None:
        return
    if "updated_at" in entity:
        entity["updated_at"] = db.clock
    if "version" in entity:
        seen = _touched_set()
        key = id(entity)
        if key not in seen:
            seen.add(key)
            entity["version"] = entity["version"] + 1


def base_entity(kind, versioned=True):
    e = {
        "id": new_id(),
        "_kind": kind,
        "_seq": db.next_seq(),
        "created_at": db.clock,
    }
    if versioned:
        e["updated_at"] = db.clock
        e["version"] = 1
    register_created(e)
    return e


def rows(collection):
    """All rows of a collection sorted by created_at ascending (PRD 2.3),
    with the insertion sequence as a stable tie-break."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
