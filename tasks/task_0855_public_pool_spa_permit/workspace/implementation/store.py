"""In-memory data store.

NO seeding of any kind.  Every collection starts empty on every boot and every
byte of state is lost when the process dies.
"""

from uuid import uuid4

from clock import LOGICAL_CLOCK


class Store(object):
    def __init__(self):
        self.operators = {}
        self.facilities = {}
        self.plan_reviews = {}
        self.permits = {}
        self.inspections = {}
        self.violations = {}
        self.water_readings = {}
        self.closure_orders = {}
        self.staff_assignments = {}
        self.compliance_artifacts = {}
        self.complaints = {}
        self.ledger_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid4())


def base_record(versioned=True):
    """Common fields: id + created_at, plus updated_at/version when versioned."""
    now = LOGICAL_CLOCK.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": DB.next_seq(),
    }
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = LOGICAL_CLOCK.now()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def ordered(rows):
    """Global list ordering: created_at ascending, tie-broken by insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
