"""In-memory data store.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded;
every entity is created through the declared API surface.
"""
import uuid

import clock

# collection name -> dict of id -> record
COLLECTIONS = (
    "units",
    "beds",
    "shifts",
    "patients",
    "authorizations",
    "admissions",
    "taper_plans",
    "studies",
    "alerts",
    "interventions",
    "markings",
    "reports",
    "exports",
    "cases",
    "votes",
)


class Store(object):
    def __init__(self):
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def all_records(self):
        for name in COLLECTIONS:
            for record in list(getattr(self, name).values()):
                yield record


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(kind, full_preamble=True):
    """Create the common record preamble (PRD 2.5)."""
    stamp = clock.now()
    record = {
        "_type": kind,
        "_seq": db.next_seq(),
        "id": new_id(),
        "created_at": stamp,
    }
    if full_preamble:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


def insert(collection, record):
    getattr(db, collection)[record["id"]] = record
    return record


def sorted_records(records):
    """Default list ordering: creation timestamp ascending (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
