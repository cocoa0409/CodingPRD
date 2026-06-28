"""Entity construction, common-field management, and serialization.

Common fields (PRD §2.4):
  id, created_at, updated_at, version  — for all entities EXCEPT StateTintRegulation,
  which carries only id and created_at (no updated_at, no version).
"""
import db


def stamp_create(record, common=True):
    """Attach system-managed common fields on creation."""
    record["id"] = db.new_id()
    record["created_at"] = db.iso(db.now())
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version by one on mutation (PRD §2.5)."""
    record["updated_at"] = db.iso(db.now())
    record["version"] = record.get("version", 0) + 1


# ---- serialization ----------------------------------------------------------
# Each entity is stored as a plain dict with already-serialized values, so the
# serializer just returns a shallow copy. This keeps the stored representation
# and the wire representation identical and avoids accidental mutation.

def serialize(record):
    return dict(record)
