"""Common entity helpers: creation stamps, mutation stamps, pagination, filters."""

from db import new_id, iso_now, next_seq
from errors import err, ERR_INVALID_REQUEST


def stamp_create(rec, common_fields=True):
    """Attach id + created_at (+ updated_at/version for full-quartet entities)."""
    rec["id"] = new_id()
    rec["created_at"] = iso_now()
    rec["_seq"] = next_seq()  # internal stable insertion order
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation stamp: refresh updated_at and bump version (full-quartet only)."""
    if "version" in rec:
        rec["updated_at"] = iso_now()
        rec["version"] = rec["version"] + 1
    return rec


def public(rec, computed=None):
    """Serialize a record to its public JSON form (strip internal keys, add computed)."""
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if computed:
        out.update(computed)
    return out


# ---- Pagination (PRD §2.3) ----------------------------------------------------

def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit out of range (1..100)")

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def sorted_by_creation(records):
    """List endpoints sort by creation timestamp ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: r["_seq"])


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
