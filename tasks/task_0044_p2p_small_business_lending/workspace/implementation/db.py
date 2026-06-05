"""In-memory data store.

Every collection is a plain dict keyed by the resource id. The store starts
EMPTY on every process boot; no seeding occurs anywhere. Tests build all state
via the declared API surface.

A monotonically increasing sequence counter gives every resource a strictly
increasing creation order, used both for stable list ordering and for
largest-remainder tie-breaks (created_at ASC -> creation sequence ASC).
"""
import uuid

from clock import clock, format_iso8601


class DB:
    def __init__(self):
        self.borrowers = {}
        self.loan_applications = {}
        self.loans = {}
        self.investors = {}
        self.investments = {}
        self.repayments = {}
        self.repayment_allocations = {}
        self.compliance_disclosures = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso8601(clock.now())


def make_common(common_fields=True):
    """Return a dict of the system-managed common fields for a freshly created resource."""
    ts = now_iso()
    base = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if common_fields:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(resource):
    """Mark a resource as mutated: refresh updated_at and bump version.

    Recomputation of a derived field counts as a mutation (PRD §2.4).
    """
    if "version" in resource:
        resource["version"] = resource.get("version", 0) + 1
    if "updated_at" in resource:
        resource["updated_at"] = now_iso()
