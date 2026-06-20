"""Common entity helpers: common fields (id/created_at/updated_at/version),
mutation bumps, pagination, and field-shape validation primitives.

PRD §2.4: every persisted resource carries id (UUID, no prefix), created_at
(ISO-8601 UTC, 3 fractional digits). Most carry updated_at and version (starts at
1, increments by one with each mutation). Recomputing a derived field is itself a
mutation that refreshes updated_at and increments version.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id, now_real_iso
from errors import err


def new_common():
    ts = now_real_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
    entity["updated_at"] = now_real_iso()
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal-only keys (those prefixed with '_') from the serialized view."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def round_half_up(value):
    """Round to whole cents, half up. value may be int/float/Decimal."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct(amount_cents, pct_decimal):
    """amount * pct, rounded half up to whole cents. pct_decimal is a Decimal."""
    return int((Decimal(amount_cents) * pct_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----- Pagination (PRD §2.3) -----

def parse_pagination(args):
    """Parse limit/offset query params. Defaults limit=10 (min 1, max 100), offset=0.
    Out-of-range / malformed values -> ERR_INVALID_REQUEST (422)."""
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit_v, offset_v


def paginate(items, limit, offset):
    """items sorted by created_at asc (caller pre-sorts). Returns (page, meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """Sort by created_at asc; _seq breaks ties deterministically (PRD §2.3)."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ----- Required-field / body helpers -----

def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_str(body, name):
    require_fields(body, [name])
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return v


def require_int(body, name):
    require_fields(body, [name])
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return v
