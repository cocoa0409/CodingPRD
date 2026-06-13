"""In-memory data store (PRD §2.4 common resource properties).

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded. start.sh re-invocation wipes all state by
virtue of being a fresh process.
"""

import uuid

import clock

# One dict per entity collection, keyed by id (UUID string, no type prefix).
customers = {}
beneficial_owners = {}
risk_assessments = {}
screening_hits = {}
accounts = {}
transactions = {}
alerts = {}
cases = {}
filings = {}
lookback_reviews = {}
lookback_review_items = {}
audit_events = {}

# Monotonic sequence used as a stable secondary sort key so that entities created
# within the same logical-clock millisecond preserve insertion order on listing.
_seq_counter = 0


def reset():
    """Wipe all collections (used at process start; defensive)."""
    global _seq_counter
    for d in (
        customers,
        beneficial_owners,
        risk_assessments,
        screening_hits,
        accounts,
        transactions,
        alerts,
        cases,
        filings,
        lookback_reviews,
        lookback_review_items,
        audit_events,
    ):
        d.clear()
    _seq_counter = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def common_create_fields():
    """id, created_at, updated_at, version for a heavyweight resource (§2.4)."""
    ts = clock.now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def light_create_fields():
    """id, created_at only — for Transaction and AuditEvent (§2.4)."""
    return {
        "id": new_id(),
        "created_at": clock.now_iso(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Advance updated_at and increment version by exactly one (§2.4)."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity["version"] + 1


def public(entity):
    """Strip internal-only keys (those starting with '_') for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
