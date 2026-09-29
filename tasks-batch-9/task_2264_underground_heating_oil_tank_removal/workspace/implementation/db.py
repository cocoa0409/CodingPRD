"""In-memory data store, logical clock, and audit-field bookkeeping.

The store starts EMPTY on every boot.  No entity is seeded, preloaded or
hardcoded anywhere: every row a test needs is built through the declared API.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import g

# PRD §2.5 — on startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "properties",
    "tank_projects",
    "disclosures",
    "permits",
    "crews",
    "work_orders",
    "laboratories",
    "soil_samples",
    "change_orders",
    "trust_fund_claims",
    "nfa_letters",
    "insurance_notifications",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    # -- logical clock ----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, moment):
        self.clock = moment

    def next_seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------------------
# audit fields (§2.4): id, created_at, updated_at, version on every resource
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def iso(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def _dirty():
    if not hasattr(g, "_dirty_rows"):
        g._dirty_rows = []
    return g._dirty_rows


def _fresh():
    if not hasattr(g, "_fresh_rows"):
        g._fresh_rows = set()
    return g._fresh_rows


def mark(entity):
    """Flag a row as mutated by this request (one version bump per request)."""
    rows = _dirty()
    if not any(row is entity for row in rows):
        rows.append(entity)


def assign(entity, field, value):
    """Write a field, flagging the row dirty only when the value really moves."""
    if entity.get(field) != value or (entity.get(field) is None) != (value is None):
        entity[field] = value
        mark(entity)


def create(table, fields):
    now = db.now()
    entity = {"id": new_id()}
    entity.update(fields)
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    getattr(db, table)[entity["id"]] = entity
    _fresh().add(entity["id"])
    return entity


def commit():
    """Apply updated_at / version bumps for every row mutated in this request."""
    rows = _dirty()
    fresh = _fresh()
    now = db.now()
    for entity in rows:
        if entity["id"] in fresh:
            continue
        entity["updated_at"] = now
        entity["version"] = entity["version"] + 1
    del rows[:]


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def _convert(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_convert(item) for item in value]
    return value


def serialize(entity):
    return {k: _convert(v) for k, v in entity.items() if not k.startswith("_")}


def sort_rows(rows):
    """Collection reads are ordered by created_at ascending (§2.3)."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
