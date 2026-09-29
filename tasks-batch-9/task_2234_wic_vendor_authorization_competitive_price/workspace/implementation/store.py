"""In-memory data store. Starts EMPTY on every boot — nothing is ever seeded."""

import uuid

import clock

COLLECTIONS = (
    "peer_groups",
    "food_categories",
    "food_items",
    "vendors",
    "price_cycles",
    "price_submissions",
    "price_ceilings",
    "monitoring_visits",
    "redemption_claims",
    "claim_lines",
    "adjustments",
    "sanction_cases",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_record(**fields):
    """Create a record with the four system-managed properties of PRD §2.4."""
    ts = clock.now()
    record = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 0) + 1
    return record


def sort_key(record):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return (record["created_at"], record["_seq"])


def ordered(collection):
    return sorted(collection.values(), key=sort_key)
