"""In-memory data store and the logical clock (PRD section 2.5).

Storage is process-local dictionaries keyed by id.  Nothing is persisted and
NOTHING is seeded: every boot starts completely empty and tests construct all
state through the declared endpoints.
"""

import datetime
import uuid

UTC = datetime.timezone.utc

# The logical clock begins here on a freshly started server (PRD section 2.5).
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.cycles = {}
        self.communities = {}
        self.parcels = {}
        self.inspectors = {}
        self.contractors = {}
        self.inspections = {}
        self.zone_evaluations = {}
        self.hardening_findings = {}
        self.notices = {}
        self.orders = {}
        self.payments = {}
        self.programs = {}
        self.enrollments = {}
        self.certificates = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The logical clock; the service never reads wall time for domain logic."""
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, audit=True):
    """Build a record with its audit columns and store it.

    ``audit`` False produces the append-only evidence shape of PRD section 2.4:
    only ``id`` and ``created_at`` (no ``updated_at``, no ``version``).
    """
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = db.clock
    if audit:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    collection[rec["id"]] = rec
    return rec


def sort_created(records):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
