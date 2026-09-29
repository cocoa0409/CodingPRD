"""Process-local in-memory store.

Every byte of state lives in this module's dictionaries and vanishes when the
process is killed. Nothing is seeded, preloaded or hardcoded: the store starts
completely empty on every boot and all rows are built through the API.
"""
from datetime import datetime

from util import UTC, fmt_dt, new_id, parse_dt, wall_now

COLLECTIONS = (
    "club_members",
    "boats",
    "rating_certificates",
    "regattas",
    "race_documents",
    "divisions",
    "entries",
    "mark_boats",
    "duty_assignments",
    "races",
    "race_results",
    "recall_events",
    "jury_panels",
    "protests",
)

# Before the first clock call the logical clock reads exactly this instant and
# it never falls back to the host machine's real time (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def reset():
    global db
    db = Store()


def now():
    """The logical clock."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def coll(name):
    return getattr(db, name)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------


def insert(collection, row, versioned=True):
    """Attach common fields and store. RecallEvent carries no updated_at/version."""
    stamp = fmt_dt(wall_now())
    row["id"] = new_id()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    coll(collection)[row["id"]] = row
    return row


def touch(row):
    """A mutation refreshes updated_at and increments version by 1 (PRD 2.9)."""
    if "version" in row:
        row["version"] = int(row["version"]) + 1
        row["updated_at"] = fmt_dt(wall_now())
    return row


def apply_changes(row, changes):
    """Write only the fields that actually change; touch the row if any did."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return coll(collection).get(row_id)


def rows(collection):
    """All rows of a collection in created_at ascending order."""
    return sorted(coll(collection).values(), key=lambda r: r["_seq"])


def find(collection, **filters):
    out = []
    for row in rows(collection):
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def D(row, field):
    """Parsed datetime of a stored datetime field, or None."""
    if row is None:
        return None
    raw = row.get(field)
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    return parse_dt(raw)
