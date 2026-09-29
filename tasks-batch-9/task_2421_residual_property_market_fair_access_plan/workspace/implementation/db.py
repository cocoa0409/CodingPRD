"""In-memory data store and the logical clock.

The store is process-local and starts COMPLETELY EMPTY on every boot: no entity
is ever seeded, preloaded or hardcoded.  Every record any caller observes was
created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from util import iso_ms

# PRD 2.6 — logical clock value at process start; never falls back to real time.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "member_insurers",
    "producers",
    "applicants",
    "cat_zones",
    "properties",
    "applications",
    "declinations",
    "inspections",
    "requirements",
    "rate_filings",
    "policies",
    "takeout_offers",
    "assessment_events",
    "assessment_allocations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_START
        self._seq = itertools.count(1)

    # --- logical clock ---------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return iso_ms(self.clock)

    def today(self):
        return self.clock.date()

    def next_seq(self):
        return next(self._seq)


db = Store()


# --- record lifecycle helpers --------------------------------------------

def new_record(fields, common=True):
    """Mint a record.  `common=True` adds updated_at + version (PRD 2.4);
    a declination record is the single exception and passes common=False."""
    stamp = db.now_iso()
    record = {"id": str(uuid.uuid4()), "created_at": stamp}
    if common:
        record["updated_at"] = stamp
        record["version"] = 1
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """A mutation (including a recomputation of a derived field, PRD 2.4/2.10):
    refresh updated_at and increment version by exactly one."""
    if record is None:
        return record
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 0) + 1
    return record


def sorted_records(collection, records=None):
    """Default list ordering: created_at ascending (PRD 2.3), with the
    insertion sequence breaking ties on an identical logical-clock stamp."""
    values = list(collection.values()) if records is None else list(records)
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
