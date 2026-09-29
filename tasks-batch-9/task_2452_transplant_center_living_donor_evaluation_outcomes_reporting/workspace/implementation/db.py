"""In-memory data store.

Every collection is a plain dict keyed by entity id.  Nothing is ever seeded,
preloaded or written to disk -- the store starts empty on every boot and every
row is created by a caller through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# The logical clock starts here on every fresh boot (PRD 2.4).
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "programs",
    "staff_members",
    "recipients",
    "waitlist_events",
    "donors",
    "evaluations",
    "chains",
    "segments",
    "rooms",
    "bookings",
    "follow_ups",
    "reviews",
    "plans",
    "claims",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Current logical UTC instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_entity(kind, fields):
    """Create a row carrying the common system fields."""
    stamp = now()
    row = {
        "id": new_id(),
        "_kind": kind,
        "_seq": db.next_seq(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    return row


def new_event(kind, fields):
    """Create a row that carries only id + created_at (no version/updated_at)."""
    row = {
        "id": new_id(),
        "_kind": kind,
        "_seq": db.next_seq(),
        "created_at": now(),
    }
    row.update(fields)
    return row


def touch(row):
    """Advance version/updated_at at most once per request for a given row."""
    if row is None:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = (row.get("_kind"), row["id"])
    if key in touched:
        return
    touched.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()


def by_created(rows):
    """Default list ordering: created_at ascending, creation sequence as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
