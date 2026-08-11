"""In-memory data store and logical clock.

Storage is process-local dicts keyed by id. Nothing is seeded at startup and
nothing is persisted anywhere; every entity is created through the API.
The logical clock starts at exactly 2026-05-01T00:00:00Z and only moves when
POST /_clock/set_current_utc is called.
"""
import uuid
from datetime import datetime, timezone

from errors import ApiError, ERR_NOT_FOUND

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.borrowers = {}
        self.loan_accounts = {}
        self.recovery_cases = {}
        self.cure_notices = {}
        self.repo_agents = {}
        self.repo_assignments = {}
        self.property_items = {}
        self.redemption_quotes = {}
        self.auction_houses = {}
        self.consignments = {}
        self.sale_records = {}
        self.deficiency_notices = {}
        self.complaints = {}
        self.ledger_entries = {}
        self.clock = CLOCK_START
        self.seq = 0  # global insertion counter; tie-breaks equal created_at

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock


def new_id():
    return str(uuid.uuid4())


def base_fields():
    """Common system fields (PRD §2.4): id/created_at/updated_at/version."""
    ts = store.clock
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Stamp a mutation: refresh updated_at and bump version."""
    entity["updated_at"] = store.clock
    entity["version"] += 1


def get_or_404(collection, rid, label="Resource"):
    entity = collection.get(rid)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found: {rid}")
    return entity


def sorted_all(collection):
    """All records sorted by created_at ascending; insertion order breaks ties."""
    return sorted(collection.values(), key=lambda e: (e["created_at"], e["_seq"]))
