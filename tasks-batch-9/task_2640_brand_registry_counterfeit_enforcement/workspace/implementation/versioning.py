"""Per-request row bookkeeping: exactly one version increment per row per
mutating request, even when an optimistic-concurrency check and a recompute
land on the same row (PRD 2.4 / 2.8)."""

from flask import g

import db


def _seen():
    bag = getattr(g, "_touched_rows", None)
    if bag is None:
        bag = set()
        g._touched_rows = bag
    return bag


def register_created(row):
    """A freshly persisted row already carries version 1; later cascade touches
    inside the same request must not push it past 1."""
    _seen().add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and increment version - once per row per request."""
    bag = _seen()
    row["updated_at"] = db.now()
    if row["id"] not in bag:
        bag.add(row["id"])
        row["version"] = row["version"] + 1
    return row


def base_row():
    stamp = db.now()
    return {"created_at": stamp, "updated_at": stamp, "version": 1}
