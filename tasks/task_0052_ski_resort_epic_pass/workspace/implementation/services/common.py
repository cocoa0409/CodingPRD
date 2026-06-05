"""Common field management and pagination helpers."""
from db import db, new_id

import errors


def new_common(extra=None):
    """Build a fresh record with full common fields (id/created_at/updated_at/version)."""
    from db import now_iso
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Mark a record as mutated: bump version and updated_at."""
    from db import now_iso
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()


def paginate(args):
    """Parse limit/offset query params (PRD §2.3). Returns (limit, offset)."""
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def sorted_by_creation(records):
    return sorted(records, key=lambda r: r.get("_seq", 0))


def page_slice(records, limit, offset):
    ordered = sorted_by_creation(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
