"""In-memory store. Every collection starts EMPTY on every boot: nothing is seeded."""
from datetime import datetime, timezone

from util import new_id


# The logical clock reads exactly 2026-08-01T00:00:00Z before it has ever been set,
# and never falls back to real wall-clock time (PRD 2.6).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.projects = {}
        self.policies = {}
        self.coverage_parts = {}
        self.interests = {}
        self.endorsements = {}
        self.claims = {}
        self.payments = {}
        self.premium_txns = {}
        self.notices = {}
        self.facilities = {}
        self.assignments = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


def new_row(with_version=True):
    """Common resource properties (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": store.clock,
    }
    if with_version:
        row["updated_at"] = store.clock
        row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    row["updated_at"] = store.clock
    row["version"] = row.get("version", 0) + 1


def ordered(rows):
    """Default collection ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_policy(collection, policy_id):
    return [r for r in collection.values() if r.get("policy_id") == policy_id]


def by_project(collection, project_id):
    return [r for r in collection.values() if r.get("project_id") == project_id]


def by_facility(collection, facility_id):
    return [r for r in collection.values() if r.get("facility_id") == facility_id]


def by_claim(collection, claim_id):
    return [r for r in collection.values() if r.get("claim_id") == claim_id]
