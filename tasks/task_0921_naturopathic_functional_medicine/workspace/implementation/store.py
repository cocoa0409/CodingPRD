"""In-memory data store. Plain dicts keyed by id. Empty on every boot.

Nothing is seeded, preloaded or hardcoded here: every row is created through a
declared endpoint.
"""

import itertools
import uuid

from clock import clock

_seq = itertools.count(1)


class Store:
    KINDS = (
        "practitioners",
        "patients",
        "intake_sections",
        "memberships",
        "lab_orders",
        "lab_results",
        "protocols",
        "protocol_items",
        "products",
        "lots",
        "dispenses",
        "encounters",
        "threads",
        "superbills",
        "referrals",
    )

    def __init__(self):
        for kind in self.KINDS:
            setattr(self, kind, {})

    def all(self, kind):
        return list(getattr(self, kind).values())


db = Store()


def new_id():
    return str(uuid.uuid4())


def _seq_next():
    return next(_seq)


def make_row(**fields):
    """Create a row carrying the common fields (id, created_at, updated_at, version)."""
    stamp = clock.stamp()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = _seq_next()
    row["_created_dt"] = clock.now()
    return row


def make_immutable_row(**fields):
    """A LabResult carries only id and created_at - no updated_at, no version."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = clock.stamp()
    row["_seq"] = _seq_next()
    row["_created_dt"] = clock.now()
    return row


def touch(row):
    """Refresh updated_at without incrementing version (cascade write)."""
    row["updated_at"] = clock.stamp()


def bump(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = clock.stamp()
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """List ordering: created_at ascending, oldest row first (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["_created_dt"], r["_seq"]))
