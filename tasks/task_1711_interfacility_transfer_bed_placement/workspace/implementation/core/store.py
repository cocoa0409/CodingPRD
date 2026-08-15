"""In-memory store.  Plain dicts keyed by id; nothing touches disk.

The store starts completely empty on every boot: no entity is seeded,
preloaded, registered or hardcoded anywhere.  Every row the tests need is
created by the tests themselves through the declared API surface.
"""

import uuid

from .clock import DEFAULT_CLOCK

COLLECTIONS = (
    "facilities",
    "beds",
    "physicians",
    "transfer_cases",
    "emtala_screenings",
    "communications",
    "bed_holds",
    "transport_dispatches",
    "insurance_notifications",
    "clinical_packets",
    "refusal_records",
    "transfer_outcomes",
    "quality_reviews",
    "diversion_events",
)


class Store(object):
    def __init__(self):
        self.now = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def ordered(self, collection):
        """PRD 2.3: created_at ascending; equal instants keep write order."""
        rows = getattr(self, collection).values()
        return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


db = Store()


def new_row(collection, fields, versioned=True):
    """A row with the common resource properties of PRD section 2.5.

    versioned rows carry created_at / updated_at / version; append-only
    records (PhysicianCommunication, RefusalRecord, TransferOutcome) carry
    only id and created_at.
    """
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now,
    }
    if versioned:
        row["updated_at"] = db.now
        row["version"] = 1
    row.update(fields)
    getattr(db, collection)[row["id"]] = row
    return row


def bump(row):
    """Count the row as mutated: version +1 and updated_at refreshed (PRD 2.5)."""
    row["version"] = row["version"] + 1
    row["updated_at"] = db.now
    return row


def find_by(collection, **conditions):
    """All rows of the collection matching every equality condition."""
    rows = getattr(db, collection).values()
    return [r for r in rows if all(r.get(k) == v for k, v in conditions.items())]


def one_by(collection, **conditions):
    rows = find_by(collection, **conditions)
    return rows[0] if rows else None
