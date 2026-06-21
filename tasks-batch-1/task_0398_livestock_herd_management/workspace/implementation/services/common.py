"""Record lifecycle helpers: common fields (id/created_at/updated_at/version),
mutation/versioning, and entity lookup.
"""
from db import db, new_id, now_iso


def base_record(common_fields=True):
    """Create a fresh record dict with id + created_at (+ updated_at/version)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),  # internal creation-order tie-break; not serialized
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a full-common-fields record as mutated: refresh updated_at, bump version."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()


def get_or_404(collection, rid):
    import errors
    if rid is None or rid not in collection:
        raise errors.not_found("Resource %s not found" % rid)
    return collection[rid]


def serialize(rec):
    """Strip internal bookkeeping keys for the response body."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
