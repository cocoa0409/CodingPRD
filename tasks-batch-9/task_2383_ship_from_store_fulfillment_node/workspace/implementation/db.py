"""In-memory store.

The store starts completely empty on every boot -- nothing is seeded, preloaded
or hardcoded. Tests build every precondition through the declared API surface.
"""
import copy
import uuid

import clock

KINDS = (
    "stores", "skus", "inventories", "packaging", "pickups", "orders",
    "order_lines", "routing_runs", "candidates", "assignments",
    "assignment_lines", "windows", "notifications",
)

# Resources that carry updated_at + version (PRD 2.5). RoutingCandidate,
# AssignmentLine and CustomerNotification are append-only and carry neither.
VERSIONED = frozenset((
    "stores", "skus", "inventories", "packaging", "pickups", "orders",
    "order_lines", "routing_runs", "assignments", "windows",
))


class Store(object):
    def __init__(self):
        self.seq = 0
        for kind in KINDS:
            setattr(self, kind, {})

    def snapshot(self):
        data = {kind: copy.deepcopy(getattr(self, kind)) for kind in KINDS}
        data["seq"] = self.seq
        return data

    def restore(self, snap):
        for kind in KINDS:
            setattr(self, kind, snap[kind])
        self.seq = snap["seq"]


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_row(kind, fields):
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["_kind"] = kind
    row["_seq"] = next_seq()
    stamp = clock.now()
    row["created_at"] = stamp
    if kind in VERSIONED:
        row["updated_at"] = stamp
        row["version"] = 1
    getattr(db, kind)[row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1


def seq_key(row):
    return row["_seq"]


def sorted_rows(collection):
    return sorted(collection, key=seq_key)


def all_of(kind):
    return sorted_rows(getattr(db, kind).values())


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, kind).get(row_id)
