"""In-memory data store, logical clock and common-field management.

Storage is process-local dictionaries keyed by id.  The store always starts
empty: no entity is ever seeded, preloaded or hardcoded at import time.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.5: at process start the logical clock reads exactly 2026-08-01T00:00:00Z.
# The server never falls back to the host wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "products",
    "ingredients",
    "product_ingredients",
    "ndi_notifications",
    "claims",
    "dossiers",
    "panels",
    "aers",
    "suppliers",
    "lots",
    "coas",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def now():
    """The logical clock: the authoritative 'now' for the whole service."""
    return store.clock


def set_clock(value):
    store.clock = value


def today():
    return now().date()


def new_id():
    # PRD 2.4: server-minted UUID with no type prefix; client ids are never honoured.
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def base_fields():
    """The four common properties every one of the eleven resources carries."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def _touched():
    bag = getattr(g, "_touched_rows", None)
    if bag is None:
        bag = set()
        g._touched_rows = bag
    return bag


def touch(row):
    """Record a mutation of `row`.

    PRD 2.4: version increments by exactly 1 on every mutation of the row,
    whether requested directly or arriving as a cascade.  A single request
    advances a given row's version at most once, no matter how many fields of
    that row the request rewrites.
    """
    if row is None:
        return
    row["updated_at"] = now()
    bag = _touched()
    if row["id"] not in bag:
        row["version"] += 1
        bag.add(row["id"])


def insert(collection, row):
    getattr(store, collection)[row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(store, collection).get(row_id)


def all_rows(collection):
    """Every row of a collection in creation order (created_at ASC, ties by arrival)."""
    rows = list(getattr(store, collection).values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
