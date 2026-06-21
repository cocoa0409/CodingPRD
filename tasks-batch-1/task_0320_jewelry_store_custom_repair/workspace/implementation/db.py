"""In-memory data store. Every byte of state lives here; a fresh process wipes it.

NO seeding/preloading at import time — the store starts empty on every boot.
Tests build all state via the API surface.
"""
import itertools
import threading
import uuid

from response import now_iso

# One dict per top-level collection, keyed by id.
customers = {}
inventory_items = {}
workbenches = {}
appraisals = {}
custom_orders = {}
repair_tickets = {}
layaway_plans = {}
trade_ins = {}
special_orders = {}
payments = {}
warranty_claims = {}
credit_ledger = {}

# Insertion order counter — used as a stable secondary sort key so records
# created within the same millisecond keep deterministic created_at order.
_seq = itertools.count(1)

# Appraisal document number sequence (per store, monotonic).
_appraisal_doc_seq = itertools.count(1)

_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def next_appraisal_doc_number():
    """'APR-' + zero-padded sequential per store."""
    n = next(_appraisal_doc_seq)
    return "APR-" + f"{n:06d}"


def new_record(common_fields=True):
    """Create a record skeleton with system fields.

    common_fields=True -> created_at, updated_at, version (PRD §2.4).
    common_fields=False -> append-only: only id + created_at (Payment, CreditLedgerEntry).
    """
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump updated_at and version by exactly 1 (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
