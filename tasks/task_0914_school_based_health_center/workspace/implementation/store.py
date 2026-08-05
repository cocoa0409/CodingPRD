"""In-memory data store.

Plain Python dicts keyed by id.  Nothing is persisted anywhere: the store is
created empty at import time and every entity a test needs is built through the
declared API surface.  There is NO seeding of any kind.
"""

import itertools
import uuid

import clock

COLLECTIONS = (
    "schools",
    "clinicians",
    "students",
    "guardians",
    "enrollments",
    "consents",
    "visits",
    "clearances",
    "doses",
    "screenings",
    "referrals",
    "charges",
    "notifications",
    "sessions",
    "reports",
)

DB = {name: {} for name in COLLECTIONS}

_SEQ = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_SEQ)


def new_row(collection, fields, with_version=True):
    """Create a row with the common fields of PRD 2.4 and store it."""
    row = {"id": new_id(), "created_at": clock.now_iso()}
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    row["_seq"] = next_seq()
    row["_collection"] = collection
    DB[collection][row["id"]] = row
    return row


_TOUCHED = set()


def begin_request():
    """Reset the per-request touched set so one row bumps version at most once."""
    _TOUCHED.clear()


def touch(row, force=False):
    """A mutation of a row: version +1 and updated_at refreshed (PRD 2.4).

    Within a single request a row's version advances exactly once, however many
    fields the operation rewrites.  ``force=True`` is used for the School row,
    whose version PRD 2.4 says advances on *every* telehealth booking or
    release, so two releases inside one cascade advance it twice.
    """
    if not force:
        if row["id"] in _TOUCHED:
            return row
        _TOUCHED.add(row["id"])
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def all_rows(collection):
    """Every row of a collection in stable creation order."""
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def order_key(row):
    return (row["created_at"], row["_seq"])
