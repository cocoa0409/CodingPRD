"""Common-fields helpers (PRD §2.4, §2.7).

Most resources carry: id (UUID, no prefix), created_at, updated_at, version
(starts at 1, +1 on every mutation that changes the resource). version and
updated_at advance together on the same atomic write.

Two append-only types (LedgerEntry, BalanceStatement) carry ONLY id +
created_at — handled in their own modules, not here.
"""
from db import db


def stamp_create(record):
    """Attach id (if absent), created_at, updated_at, version=1."""
    if "id" not in record:
        record["id"] = db.new_id()
    ts = db.now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mutation bump: advance version + updated_at together (PRD §2.7)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = db.now_iso()
