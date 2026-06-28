"""Common entity helpers: system fields, mutation bumps, serialization (PRD §2.4, §2.8)."""
from db import store, new_id, now_iso


def base_fields(with_version=True):
    """Create the common system-managed fields (PRD §2.4).

    id (UUID, no prefix), created_at, updated_at, version (starts at 1).
    Payment is the exception (with_version=False): only id and created_at.
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation bump: refresh updated_at and increment version (PRD §2.8)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()


def public(rec):
    """Strip internal-only keys (those starting with underscore) for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def paginate(items, limit, offset):
    """Sort by created_at asc (stable via _seq) and slice (PRD §2.3)."""
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], total
