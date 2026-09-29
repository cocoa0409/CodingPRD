"""In-memory store, id/timestamp management and the server-side logical clock.

The store starts completely empty on every boot.  Nothing is seeded, preloaded or
hardcoded here: every entity is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD §2.4 — before any client sets it, the logical clock reads exactly this instant
# and it never falls back to real (wall-clock) time.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "service_members",
    "orders",
    "counseling_sessions",
    "entitlements",
    "tsps",
    "capacity_blocks",
    "shipments",
    "pro_gear_declarations",
    "sit_authorizations",
    "claims",
    "claim_items",
    "ppm_submissions",
    "notifications",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.logical_clock = LOGICAL_CLOCK_DEFAULT
        self._seq = itertools.count(1)


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def clock():
    """The single server-side logical clock (PRD §2.4)."""
    return db.logical_clock


def set_clock(value):
    db.logical_clock = value
    return db.logical_clock


def next_seq():
    return next(db._seq)


def base_record():
    """The four server-managed common properties of every persisted resource."""
    ts = wall_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def _touched_set():
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    return touched


def mark_fresh(rec):
    """A record created inside this request keeps version 1."""
    _touched_set().add(rec["id"])


def touch(rec):
    """Refresh updated_at and increment version — once per record per request."""
    if rec is None:
        return rec
    touched = _touched_set()
    if rec["id"] in touched:
        return rec
    touched.add(rec["id"])
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = wall_now()
    return rec


def by_seq(records):
    """Default list ordering: created_at ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: r["_seq"])
