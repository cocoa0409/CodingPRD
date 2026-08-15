"""Record construction, mutation bookkeeping, and serialization helpers."""
from db import store
from util import new_id, now_iso


def new_record(table, fields):
    """Create a record with common system fields and store it."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["updated_at"] = now_iso()
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    table[rec["id"]] = rec
    return rec


def new_ledger_row(fields):
    """HourCredit rows carry only id and created_at (no updated_at/version)."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = store.next_seq()
    store.hour_credits[rec["id"]] = rec
    return rec


def touch(rec):
    """Any change to a resource refreshes updated_at and increments version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal bookkeeping keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
