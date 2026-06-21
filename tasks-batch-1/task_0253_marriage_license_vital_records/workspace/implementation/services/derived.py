"""Derived-count recomputation helpers (PRD 3.1, 3.5).

Two flavors:
  * compute_*  -> pure read of the current count (no mutation).
  * recompute_and_store_* -> persist the count on the entity, bumping
    version/updated_at when the value actually changed (used as an operation
    side effect, PRD 2.5).
"""
from db import store
from util import touch


def compute_returns_filed_count(officiant_id):
    return sum(
        1 for r in store.returns.values()
        if r["officiant_id"] == officiant_id and r["status"] == "ACCEPTED"
    )


def compute_amendment_count(record_id):
    return sum(
        1 for a in store.amendments.values()
        if a["record_id"] == record_id and a["status"] == "APPLIED"
    )


def compute_certified_copies_issued(record_id):
    return sum(
        1 for c in store.certified_copies.values()
        if c["record_id"] == record_id and c["status"] == "ISSUED"
    )


def recompute_and_store_returns_filed_count(officiant):
    val = compute_returns_filed_count(officiant["id"])
    officiant["returns_filed_count"] = val
    touch(officiant)


def recompute_and_store_amendment_count(record):
    val = compute_amendment_count(record["id"])
    if record.get("amendment_count") != val:
        record["amendment_count"] = val
        touch(record)
    else:
        record["amendment_count"] = val


def recompute_and_store_certified_copies_issued(record):
    val = compute_certified_copies_issued(record["id"])
    if record.get("certified_copies_issued") != val:
        record["certified_copies_issued"] = val
        touch(record)
    else:
        record["certified_copies_issued"] = val
