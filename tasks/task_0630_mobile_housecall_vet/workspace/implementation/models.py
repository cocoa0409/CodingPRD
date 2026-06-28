"""Entity construction, mutation bookkeeping, and serialization.

Every full entity carries id/created_at/updated_at/version. ControlledMedLog is
the lean append-only exception (id + created_at only).
"""
import db


def stamp_new(record):
    """Attach common system fields to a freshly created full entity."""
    ts = db.now_iso()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.seq()  # internal insertion order, never serialized
    return record


def touch(record):
    """Register a mutation: refresh updated_at, bump version by 1."""
    record["updated_at"] = db.now_iso()
    record["version"] = record["version"] + 1


def public(record):
    """Strip internal fields (those prefixed with '_') for the API response."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def sort_key_created(record):
    """Stable created_at ASC ordering, tie-broken by insertion sequence.

    Never tie-broken by id (PRD §3.3 / §3.7).
    """
    return (record["created_at"], record.get("_seq", 0))
