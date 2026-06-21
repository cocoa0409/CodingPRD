"""Entity record construction, common-field management, and serialization.

Common fields (PRD §2.4): id (UUID, no prefix), created_at, updated_at,
version (starts at 1, +1 per mutation). SoftCredit is leaner: only id +
created_at + reversed (no updated_at, no version) per §2.4.

Internal bookkeeping keys are prefixed with '_' and stripped on serialization.
"""

import db


# Fields that are internal-only and must never appear in API output.
_INTERNAL_PREFIX = "_"


def new_record(extra=None, common=True):
    """Build a base record dict with common fields. `extra` carries the
    entity-specific fields. version starts at 1."""
    now = db.clock_iso()
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Mark a record mutated: bump updated_at and version (if it has them)."""
    rec["updated_at"] = db.clock_iso()
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def serialize(rec):
    """Return a public copy of a record with internal '_'-prefixed keys removed."""
    return {k: v for k, v in rec.items() if not k.startswith(_INTERNAL_PREFIX)}


def serialize_list(rows):
    return [serialize(r) for r in rows]
