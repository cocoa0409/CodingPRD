"""In-memory data store. Every byte is wiped on each fresh boot.

NEVER seed/preload/hardcode entities here — tests build all state via the API.
"""
import itertools
import uuid

from response import now_iso

# One dict per entity collection, keyed by id.
households = {}
owners = {}
patients = {}
wellness_plans = {}
appointments = {}
vaccinations = {}
prescriptions = {}
estimates = {}
surgeries = {}
boarding_stays = {}
lab_orders = {}
invoices = {}
operatories = {}
kennels = {}

# Monotonic creation sequence so created_at ties have a stable, faithful order
# (the PRD breaks several ties by "then by created_at ASC"; using a per-record
# integer sequence guarantees a deterministic, insertion-faithful tiebreak even
# when several records share the same millisecond timestamp).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_common():
    """Common system fields (PRD §2.4): id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
