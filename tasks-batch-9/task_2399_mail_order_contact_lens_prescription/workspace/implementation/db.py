"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  The only non-entity state is the logical clock (PRD section 2.5),
which reads 2026-08-01T00:00:00Z until an administrator sets it.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.insurance_plans = {}
        self.products = {}
        self.lens_equivalences = {}
        self.prescribers = {}
        self.customers = {}
        self.prescriptions = {}
        self.verification_requests = {}
        self.orders = {}
        self.reorder_holds = {}
        self.auto_reorder_schedules = {}
        self.return_requests = {}
        self.reimbursement_claims = {}
        self.prescriber_disputes = {}
        self.compliance_events = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def now():
    """Current logical clock instant."""
    return db.clock


def today():
    return db.clock.date()


def set_clock(value):
    db.clock = value


def sort_rows(rows):
    """Deterministic created_at ascending ordering with insertion-order tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def make_row(fields, common=True):
    row = dict(fields)
    row["id"] = new_id()
    if common:
        stamp = now()
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at and increment version."""
    if row is None:
        return
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
