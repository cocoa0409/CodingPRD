"""In-memory data store.

Every entity is held in a dict keyed by its server-minted UUID.  The store
starts EMPTY on every boot — nothing is seeded, preloaded, or hardcoded.  All
entities are created by tests via the declared API surface.

A monotonically increasing per-record `_seq` is stored alongside each record so
that ordering ties on identical `created_at` timestamps resolve deterministically
by insertion order (used only where the PRD pins `created_at ASC`; the record id
is never used as a sort key per the payment-waterfall rule).
"""
import threading
import uuid

import clock
from timeutil import iso_now

# One dict per entity type.
officers = {}
supervisees = {}
risk_assessments = {}
conditions = {}
check_ins = {}
drug_tests = {}
violations = {}
sanctions = {}
obligations = {}
payments = {}
court_reports = {}
transfers = {}
early_terminations = {}

_lock = threading.RLock()
_seq_counter = 0


def lock():
    return _lock


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def common_create_fields(versioned=True):
    """Return id/created_at/(updated_at/version) for a freshly minted record."""
    ts = iso_now(clock.now())
    fields = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if versioned:
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version by one.

    PRD §2.4: every mutation refreshes updated_at and increments version by one,
    including computed-field recomputations.
    """
    record["updated_at"] = iso_now(clock.now())
    record["version"] = record.get("version", 1) + 1
