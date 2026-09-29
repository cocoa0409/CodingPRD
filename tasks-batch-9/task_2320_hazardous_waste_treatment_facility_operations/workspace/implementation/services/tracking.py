"""Mutation bookkeeping.

PRD 2.4: recomputation of a derived field counts as a mutation of the row that
owns it -- so any row whose observable projection changes during a request gets
its updated_at and version advanced exactly once. Rows mutated directly are
touched explicitly; everything else is caught by comparing a before/after
snapshot of every versioned row's projection.
"""

import json

from flask import g

from db import VERSIONED, db, now
from services.derive import PROJECTORS


def _signature(collection, row):
    data = dict(PROJECTORS[collection](row))
    data.pop("updated_at", None)
    data.pop("version", None)
    return json.dumps(data, sort_keys=True, default=str)


def snapshot():
    snap = {}
    for collection in VERSIONED:
        for row_id, row in db.collection(collection).items():
            snap[(collection, row_id)] = _signature(collection, row)
    return snap


def begin():
    g.touched = set()
    g.tracked = set()


def touch(collection, row):
    """Explicitly advance a row that this request mutated."""
    key = (collection, row["id"])
    if key in getattr(g, "touched", set()):
        return
    if hasattr(g, "touched"):
        g.touched.add(key)
    # Rows created inside this request stay at version 1.
    if key in getattr(g, "tracked", set()):
        row["version"] += 1
        row["updated_at"] = now()


def settle(before):
    touched = getattr(g, "touched", set())
    for key, signature in before.items():
        if key in touched:
            continue
        collection, row_id = key
        row = db.collection(collection).get(row_id)
        if row is None:
            continue
        if _signature(collection, row) != signature:
            row["version"] += 1
            row["updated_at"] = now()
