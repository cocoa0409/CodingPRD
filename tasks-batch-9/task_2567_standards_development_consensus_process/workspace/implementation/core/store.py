"""In-memory data store, logical clock and version/timestamp bookkeeping.

Storage is process-local Python dictionaries keyed by uuid. Nothing is persisted
and NOTHING IS SEEDED: every boot starts with twelve empty collections and the
logical clock at exactly 2026-08-01T00:00:00Z.
"""

import datetime as _dt
import uuid

from flask import g

from .util import iso

CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

COLLECTIONS = (
    "participants",
    "committees",
    "memberships",
    "work_items",
    "drafts",
    "ballots",
    "votes",
    "comments",
    "public_reviews",
    "patent_disclosures",
    "appeals",
    "maintenance_items",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def collection(self, name):
        return getattr(self, name)


db = Store()


def now():
    """The logical clock. The server never falls back on real system time."""
    return db.clock


def now_iso():
    return iso(db.clock)


def new_id():
    return str(uuid.uuid4())


def _marks():
    marks = getattr(g, "_touched_rows", None)
    if marks is None:
        marks = set()
        g._touched_rows = marks
    return marks


def insert(collection_name, fields):
    """Create a row with the four common fields and store it."""
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = db.next_seq()
    db.collection(collection_name)[row["id"]] = row
    # A row created inside this request never also takes a version bump.
    _marks().add(row["id"])
    return row


def touch(row):
    """Advance version (at most once per request) and refresh updated_at."""
    if row is None:
        return row
    marks = _marks()
    if row["id"] not in marks:
        marks.add(row["id"])
        row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()
    return row


def public(row):
    """Strip private bookkeeping keys before serialisation."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def rows(collection_name):
    """All rows of a collection in ascending created_at (creation) order."""
    values = list(db.collection(collection_name).values())
    values.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return values


def newest(candidates):
    """Most recently created row of an iterable, or None."""
    best = None
    for row in candidates:
        if best is None or row["_seq"] > best["_seq"]:
            best = row
    return best


def find(collection_name, **filters):
    """All rows matching every keyword filter, in creation order."""
    out = []
    for row in rows(collection_name):
        if all(row.get(key) == value for key, value in filters.items()):
            out.append(row)
    return out
