"""In-memory data store, the logical clock and the common-field machinery.

Storage is process-local Python dictionaries only. Nothing is persisted and
nothing is seeded: a fresh process starts with a completely empty store, which
is exactly what the per-test-server harness relies on.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD §2.4 — before any client sets it the logical clock reads exactly this.
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = LOGICAL_CLOCK_EPOCH
        self.clock_echo = None          # raw string last supplied by a client
        self._seq = itertools.count(1)

        self.departments = {}
        self.primal_purchases = {}
        self.cutting_tests = {}
        self.cutting_test_lines = {}
        self.retail_items = {}
        self.case_plans = {}
        self.case_plan_lines = {}
        self.trim_lots = {}
        self.grind_runs = {}
        self.grind_inputs = {}
        self.temperature_logs = {}
        self.case_failures = {}
        self.pre_orders = {}
        self.shrink_reconciliations = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def now():
    """The logical clock instant. Never wall-clock time (PRD §2.4)."""
    return db.clock


def today():
    return db.clock.date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


# --------------------------------------------------------------------------
# entity helpers
# --------------------------------------------------------------------------

def new_id():
    """A UUID string with no type prefix of any kind (PRD §2.4)."""
    return str(uuid.uuid4())


def make(kind, fields, common=True):
    """Build a new entity dict.

    ``common=True`` gives the full ``created_at`` / ``updated_at`` / ``version``
    set. ``common=False`` is the temperature-log exception: only ``id`` and
    ``created_at``.
    """
    entity = {"id": new_id()}
    entity.update(fields)
    stamp = now_iso()
    entity["created_at"] = stamp
    if common:
        entity["updated_at"] = stamp
        entity["version"] = 1
    entity["_kind"] = kind
    entity["_seq"] = db.next_seq()
    entity["_new"] = True
    _fresh().append(entity)
    return entity


def _dirty():
    if not hasattr(g, "_dirty_entities"):
        g._dirty_entities = []
    return g._dirty_entities


def _fresh():
    if not hasattr(g, "_fresh_entities"):
        g._fresh_entities = []
    return g._fresh_entities


def clear_new_flags():
    """A resource is only 'new' for the request that created it."""
    for entity in _fresh():
        entity.pop("_new", None)
    g._fresh_entities = []


def mark(entity):
    """Record that ``entity`` was mutated during this request.

    A resource mutated any number of times inside a single request advances its
    ``version`` by exactly one (PRD §2.4).
    """
    if entity is None:
        return
    if entity.get("_new"):
        return
    bucket = _dirty()
    for existing in bucket:
        if existing is entity:
            return
    bucket.append(entity)


def flush():
    """Apply the pending ``updated_at`` / ``version`` bumps."""
    bucket = _dirty()
    if bucket:
        stamp = now_iso()
        for entity in bucket:
            if "version" in entity:
                entity["version"] = entity["version"] + 1
            if "updated_at" in entity:
                entity["updated_at"] = stamp
        g._dirty_entities = []
    clear_new_flags()


def sort_rows(rows):
    """Default list ordering: created_at ascending (PRD §2.3).

    ``_seq`` is a deterministic tie-break for rows minted at the same logical
    instant, preserving insertion order.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
