"""In-memory store. Starts completely empty on every boot - nothing is seeded."""

import itertools
import uuid
from datetime import datetime, timezone

# PRD section 2.5: the logical clock starts at this instant on a fresh boot.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "life_support_systems",
    "water_quality_readings",
    "exhibits",
    "species",
    "institutions",
    "collection_plan_entries",
    "acquisition_requests",
    "permits",
    "specimens",
    "quarantine_cases",
    "husbandry_logs",
    "veterinary_cases",
    "transfer_requests",
    "interaction_sessions",
    "accreditation_audits",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


def new_row(with_common=True):
    row = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
    }
    if with_common:
        row["updated_at"] = db.clock
        row["version"] = 1
    return row


def touch(row):
    """Register a mutation: bump updated_at and version (PRD section 2.4)."""
    if "version" in row:
        row["updated_at"] = db.clock
        row["version"] = row["version"] + 1
    return row


def ordered(collection, predicate=None, reverse=False):
    rows = list(getattr(db, collection).values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=reverse)
    return rows
