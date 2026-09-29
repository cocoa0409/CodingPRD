"""In-memory storage and the logical clock.

Storage is process-local Python dicts keyed by id.  Nothing is persisted to
disk, and no entity data is ever seeded at startup: every collection starts
empty on every boot.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = CLOCK_EPOCH

    def reset(self):
        self.current = CLOCK_EPOCH

    def set(self, dt):
        self.current = dt.astimezone(timezone.utc)
        return self.current

    def now(self):
        return self.current

    def stamp(self):
        """The canonical textual form of the current logical instant."""
        return fmt_instant(self.current)

    def meta_stamp(self):
        return fmt_millis(self.current)


def fmt_instant(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_millis(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


CLOCK = Clock()


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "permit_terms",
    "control_measures",
    "outfalls",
    "observations",
    "cases",
    "sites",
    "facilities",
    "inspections",
    "enforcement_actions",
    "accounts",
    "credit_applications",
    "annual_reports",
)


class Store:
    def __init__(self):
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)

    def reset(self):
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})


DB = Store()


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------


def new_row(fields):
    stamp = CLOCK.stamp()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    row.update(fields)
    _mark(row["id"])
    return row


def touch(row):
    """Record a mutation of a row: bump version once per request, restamp."""
    row["updated_at"] = CLOCK.stamp()
    if not _mark(row["id"]):
        row["version"] = row.get("version", 1) + 1
    return row


def _mark(row_id):
    try:
        touched = g.touched_rows
    except (RuntimeError, AttributeError):
        return False
    if row_id in touched:
        return True
    touched.add(row_id)
    return False


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def rows_sorted(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
