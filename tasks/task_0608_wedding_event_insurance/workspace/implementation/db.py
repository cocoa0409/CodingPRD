"""In-memory data store. State is wiped on every process boot — NO seeding.

Each entity collection is a dict keyed by UUID id. Insertion order is preserved
by Python dicts, so created_at-ascending order is the natural iteration order.
"""
import uuid

from clock import clock
from timeutil import fmt


class Store:
    def __init__(self):
        # One dict per entity type.
        self.coverage_products = {}
        self.vendors = {}
        self.force_majeure_events = {}
        self.policies = {}
        self.event_profiles = {}
        self.coverages = {}
        self.riders = {}
        self.certificates = {}
        self.endorsements = {}
        self.claims = {}
        self.claim_documents = {}
        self.ledger_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return fmt(clock.now())


def new_common(versioned=True):
    """Return the system-managed common fields for a freshly created entity.

    versioned=True  -> id, created_at, updated_at, version (PRD §2.4)
    versioned=False -> id, created_at only (immutable append-only records)
    """
    created = now_iso()
    base = {"id": new_id(), "created_at": created}
    if versioned:
        base["updated_at"] = created
        base["version"] = 1
    return base


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD §2.4 / §2.6)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
