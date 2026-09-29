"""In-memory data store.

Every collection starts empty on every boot: nothing is seeded, preloaded or
hardcoded. Tests build all preconditions through the declared API surface.
"""

import uuid

import clock

COLLECTIONS = (
    "insureds",
    "disclosure_packages",
    "litigation_events",
    "submissions",
    "quotes",
    "exclusion_terms",
    "policies",
    "coverage_parts",
    "layers",
    "claims",
    "circumstance_reports",
    "defense_invoices",
    "settlement_proposals",
    "runoff_endorsements",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.policy_number_counter = 0
        self.epoch = 0
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_policy_number(self):
        self.policy_number_counter += 1
        return "DO-%06d" % self.policy_number_counter


store = Store()


def new_id():
    return str(uuid.uuid4())


def insert(collection, record, common_fields=True):
    """Mint id/created_at (and updated_at/version when the entity carries them)."""
    record["id"] = new_id()
    now = clock.now()
    record["created_at"] = now
    if common_fields:
        record["updated_at"] = now
        record["version"] = 1
    record["_seq"] = store.next_seq()
    getattr(store, collection)[record["id"]] = record
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4, 2.9)."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 0) + 1
    return record


def sort_key(record):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return (record["created_at"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)
