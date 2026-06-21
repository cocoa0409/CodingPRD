"""Record construction and mutation helpers (PRD §2.4).

Most resources carry id/created_at/updated_at/version. Two append-only event
records — FinanceTransaction and LayawayInstallment — carry ONLY id/created_at.
"""
from db import store, new_id


def base_record(extra=None):
    """Create a full versioned record: id, created_at, updated_at, version."""
    now = store.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def event_record(extra=None):
    """Create an append-only event record: id, created_at only (no version/updated_at)."""
    now = store.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(record):
    """Register a mutation: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = store.now()
    record["version"] = record.get("version", 1) + 1
    return record
