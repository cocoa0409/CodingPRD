"""In-memory data store, logical clock and common-field helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: the store is empty on every boot.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.5: the logical clock starts at this instant on every boot.
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "programs",
    "rounds",
    "landowners",
    "parcels",
    "applications",
    "negotiation_rounds",
    "appraisals",
    "funding_sources",
    "funding_commitments",
    "closing_requirements",
    "easements",
    "monitoring_visits",
    "violations",
    "amendments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    """PRD 2.4: server-minted UUID, no prefix."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


def clock():
    return db.clock


def base_row(with_version=True):
    now = iso(wall_now())
    row = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if with_version:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """PRD 2.4: bump updated_at and version.

    A row is bumped at most once per request even when several cascade rules
    touch it, so `version` moves by exactly one per mutating call.
    """
    if row is None:
        return row
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    key = row.get("id")
    row["updated_at"] = iso(wall_now())
    if key in touched:
        return row
    touched.add(key)
    row["version"] = int(row.get("version", 1)) + 1
    return row


def sort_rows(rows, keyfunc):
    return sorted(rows, key=keyfunc)


def created_key(row):
    return (row["created_at"], row["_seq"])
