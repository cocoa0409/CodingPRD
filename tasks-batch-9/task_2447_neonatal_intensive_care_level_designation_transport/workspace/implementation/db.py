"""In-memory data store.

The store starts EMPTY on every boot. No entity is ever seeded, preloaded or
hardcoded — every row is created by a client through the declared endpoints.
"""
import itertools
import uuid

import clock


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.units = {}
        self.standards = {}
        self.credentials = {}
        self.assets = {}
        self.reviews = {}
        self.referrals = {}
        self.reservations = {}
        self.runs = {}
        self.admissions = {}
        self.milk_batches = {}
        self.escalations = {}
        self.reports = {}
        self.enrollments = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    """Common fields (PRD 2.4): id, created_at, updated_at, version."""
    ts = clock.now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation: refresh updated_at from the logical clock and bump version."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def ordered(records):
    """Default list ordering: created_at ascending (id is never consulted)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
