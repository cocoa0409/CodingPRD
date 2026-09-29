"""In-memory store, logical clock and per-request mutation bookkeeping.

The store is created empty on every boot and is never seeded.
"""
from flask import g

from util import CLOCK_EPOCH, new_id


class Store(dict):
    """A plain id -> row map with insertion-ordered listing."""

    def add(self, row):
        self[row["id"]] = row
        _record_insert(self, row["id"])
        return row

    def all(self):
        return list(self.values())


class Database(object):
    def __init__(self):
        self.models = Store()
        self.profiles = Store()
        self.obligations = Store()
        self.parts = Store()
        self.compats = Store()
        self.revisions = Store()
        self.assessments = Store()
        self.orders = Store()
        self.lines = Store()
        self.acks = Store()
        self.providers = Store()
        self.certs = Store()
        self.cases = Store()
        self.current_utc = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Database()


def now():
    """The logical clock — every temporal rule reads this, never the wall clock."""
    return db.current_utc


# --------------------------------------------------------------------------
# per-request mutation bookkeeping
# --------------------------------------------------------------------------

def _dirty():
    if not hasattr(g, "_dirty_rows"):
        g._dirty_rows = {}
    return g._dirty_rows


def _fresh():
    if not hasattr(g, "_fresh_rows"):
        g._fresh_rows = set()
    return g._fresh_rows


def _snapshots():
    if not hasattr(g, "_row_snapshots"):
        g._row_snapshots = {}
    return g._row_snapshots


def _inserts():
    if not hasattr(g, "_row_inserts"):
        g._row_inserts = []
    return g._row_inserts


def _record_insert(store, row_id):
    try:
        _inserts().append((store, row_id))
    except RuntimeError:
        pass


def touch(row):
    """Mark a row as mutated by this request; it gets exactly one version bump.

    The bump happens eagerly, at the moment the row is first marked, so that
    anything serialized later in the same request already reports the
    post-mutation version and updated_at. A refusal rolls the row back to the
    snapshot taken here, so a refused request leaves nothing changed.
    """
    if row is None:
        return row
    key = id(row)
    dirty = _dirty()
    if key not in dirty:
        dirty[key] = row
        if key not in _fresh():
            _snapshots()[key] = dict(row)
            if "version" in row:
                row["version"] = row.get("version", 1) + 1
            if "updated_at" in row:
                row["updated_at"] = now()
    return row


def setf(row, field, value):
    """Assign a field, marking the row dirty only when the value actually changes."""
    if row.get(field) != value:
        touch(row)
        row[field] = value
        return True
    return False


def base_row(with_common=True):
    row = {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}
    if with_common:
        row["updated_at"] = now()
        row["version"] = 1
    _fresh().add(id(row))
    return row


def commit():
    """Accept this request's mutations; versions were already bumped by touch()."""
    _dirty().clear()
    _snapshots().clear()
    _inserts()[:] = []


def rollback():
    """Undo this request's mutations so a refusal changes nothing."""
    snapshots = _snapshots()
    for key, row in list(_dirty().items()):
        snapshot = snapshots.get(key)
        if snapshot is None:
            continue
        row.clear()
        row.update(snapshot)
    for store, row_id in reversed(_inserts()):
        store.pop(row_id, None)
    _dirty().clear()
    snapshots.clear()
    _inserts()[:] = []


# --------------------------------------------------------------------------
# ordering helpers
# --------------------------------------------------------------------------

def sort_key(row):
    return (row["created_at"], row.get("_seq", 0))


def ordered(rows):
    return sorted(rows, key=sort_key)
