"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded. Every row is created by an API request.
"""
import uuid
from decimal import Decimal

import clock

ZERO = Decimal("0.00")


class Store:
    def __init__(self):
        self.open_policies = {}
        self.commodity_classes = {}
        self.vessels = {}
        self.ports = {}
        self.surveyors = {}
        self.certificates = {}
        self.accumulation_entries = {}
        self.premium_declarations = {}
        self.claim_files = {}
        self.damage_documents = {}
        self.survey_orders = {}
        self.ga_events = {}
        self.ga_postings = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_row(versioned=True):
    ts = clock.now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """A mutation of a row: refresh updated_at and increment version by one."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """PRD 2.3: list endpoints return rows in created_at ascending order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def ordered_by(rows, field):
    return sorted(rows, key=lambda r: (r[field], r["_seq"]))
