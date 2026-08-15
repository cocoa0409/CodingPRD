"""In-memory data store.

The store starts EMPTY on every boot — no seeding. All state is constructed
through the declared API surface. Records are plain dicts; internal bookkeeping
fields are prefixed with an underscore and never serialized.
"""

import uuid

import clock


class Store:
    def __init__(self):
        self.providers = {}
        self.criteria_sets = {}
        self.guideline_versions = {}
        self.requests = {}
        self.determinations = {}
        self.conferences = {}
        self.appeals = {}
        self.gold_card_evaluations = {}
        self.arrangements = {}
        self.findings = {}
        self.events = {}
        self._seq = 0

    def next_seq(self):
        """Monotonic insertion counter; stable tiebreak for created_at ordering."""
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """Bare UUID with no type prefix."""
    return str(uuid.uuid4())


def base_record():
    """id + created_at/updated_at/version common fields (standard resources)."""
    now = clock.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def lean_record():
    """id + created_at only — GoldCardEvaluation and ComplianceEvent carry no
    updated_at/version (immutable snapshot / append-only audit record)."""
    return {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = clock.now()
    rec["version"] += 1
