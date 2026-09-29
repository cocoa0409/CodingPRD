"""In-memory data store, logical clock and per-request mutation bookkeeping.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every row is created through the declared API surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from flask import g

# A single global lock serialises request handling so that derived-counter
# recomputation is always observed atomically.
LOCK = threading.RLock()

# PRD 2.5: before the clock has ever been set it reads exactly this instant and
# it never falls back to real time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.rooms = {}
        self.statutes = {}
        self.locations = {}
        self.custodians = {}
        self.cases = {}
        self.items = {}
        self.determinations = {}
        self.transfers = {}
        self.orders = {}
        self.claims = {}
        self.sessions = {}
        self.discrepancies = {}
        self.chain_events = {}
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


db = Store()


def now():
    return db.clock


def set_clock(instant):
    previous = db.clock
    db.clock = instant
    return previous


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db.seq)


# --------------------------------------------------------------------------
# per-request bookkeeping
# --------------------------------------------------------------------------

def begin_request():
    g.dirty = {}
    g.fresh = set()


def _dirty():
    if not hasattr(g, "dirty"):
        g.dirty = {}
    return g.dirty


def _fresh():
    if not hasattr(g, "fresh"):
        g.fresh = set()
    return g.fresh


def mark(entity):
    """Record that `entity` was mutated by this request and advance its version.

    PRD 2.4: `version` increments by one on every mutation — including
    mutations that only touch derived counters.  A row mutated several times
    inside one request still advances exactly once, and a row created by this
    request stays at version 1.
    """
    if entity is None:
        return
    dirty = _dirty()
    key = id(entity)
    if key in dirty:
        return
    dirty[key] = entity
    if key in _fresh():
        return
    if "version" in entity:
        entity["version"] = entity["version"] + 1
        entity["updated_at"] = now()


def commit():
    """Per-request bookkeeping is applied eagerly by `mark`; this only clears."""
    g.dirty = {}


def new_entity(kind, fields, common_fields=True):
    entity = {
        "id": new_id(),
        "_kind": kind,
        "_seq": next_seq(),
        "created_at": now(),
    }
    if common_fields:
        entity["updated_at"] = now()
        entity["version"] = 1
    entity.update(fields)
    _fresh().add(id(entity))
    return entity


def sort_rows(rows):
    """Default ordering: creation timestamp ascending, insertion order as the
    stable tie-break (the logical clock may stand still or be rewound)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
