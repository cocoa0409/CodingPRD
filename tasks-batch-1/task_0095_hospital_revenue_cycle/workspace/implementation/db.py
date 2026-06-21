"""In-memory data store. Every byte of state lives here in module-level dicts
keyed by id. start.sh re-invocation starts a fresh process, so all state is
wiped on every boot. NO seeding/preloading is performed anywhere."""
import uuid

import clock

# One dict per entity collection, keyed by id.
payers = {}
patients = {}
insurance_policies = {}
benefit_accumulators = {}
encounters = {}
eligibility_checks = {}
charges = {}
coding_assignments = {}
claims = {}
claim_lines = {}
patient_statements = {}
payments = {}
write_offs = {}

# Monotonic sequence to break created_at ties deterministically (oldest-first
# ordering by created_at; the sequence preserves insertion order when two
# records share the same clock instant — common under the frozen test clock).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def base_record(common_fields=True):
    """Build the common system fields for a new record.

    common_fields=True  -> id, created_at, updated_at, version (mutable accounts)
    common_fields=False -> id, created_at only (immutable ledger entries:
                           Payment and WriteOff carry no updated_at / version).
    """
    ts = clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4 / 2.9)."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1
