"""In-memory store. Plain dicts keyed by id; empty on every boot.

Nothing is seeded, preloaded or hardcoded here: every row is created by a
request through the declared API surface.
"""
from datetime import datetime

from util import UTC, new_id

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "programs",
    "households",
    "members",
    "reviews",
    "entries",
    "sites",
    "shifts",
    "volunteers",
    "assignments",
    "enrollments",
    "applications",
    "cost_entries",
    "grants",
)


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = DB()


def stamp(row):
    """Attach identity and common fields to a freshly built row."""
    row["id"] = new_id()
    row["created_at"] = db.clock
    row["updated_at"] = db.clock
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Accepted mutation: bump version by exactly 1 and refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = db.clock
    return row


def bump(row):
    """Version a row at most once per request, however many hops touch it."""
    try:
        from flask import g
        seen = getattr(g, "bumped_rows", None)
        if seen is None:
            seen = set()
            g.bumped_rows = seen
    except Exception:
        seen = None
    if seen is not None:
        key = id(row)
        if key in seen:
            row["updated_at"] = db.clock
            return row
        seen.add(key)
    return touch(row)


def fresh(row):
    """Mark a freshly created row so a later cascade will not version it."""
    try:
        from flask import g
        seen = getattr(g, "bumped_rows", None)
        if seen is None:
            seen = set()
            g.bumped_rows = seen
        seen.add(id(row))
    except Exception:
        pass
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (creation order on ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
