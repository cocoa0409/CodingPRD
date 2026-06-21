"""Shared utilities: id minting, timestamps, money rounding, datetime parsing,
common-field stamping, and pagination.
"""
import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err
from response import now_iso

# Monotonic creation counter — gives a stable tiebreaker for equal-millisecond
# created_at timestamps so list/sort ordering and pooled-tip created_at ranking
# are deterministic. Reset on each fresh process (module import).
_seq = itertools.count()


def new_id():
    """Server-minted UUID, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer cent.

    Accepts int/float/Decimal. A fractional remainder of exactly one half
    rounds away from zero to the next whole cent (PRD §2.6).
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stamp_create(obj, with_version=True):
    """Attach system-managed common fields on creation (PRD §2.4).

    id / created_at / updated_at / version. ProductSale opts out of
    updated_at + version by passing with_version=False (it keeps id+created_at).
    """
    obj["id"] = new_id()
    ts = now_iso()
    obj["created_at"] = ts
    obj["_seq"] = next(_seq)  # internal ordering tiebreaker, not serialized
    if with_version:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive inputs are treated as UTC.
    Raises ERR_INVALID_REQUEST on anything unparseable.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Serialization: strip internal-only keys before returning a resource.
# ---------------------------------------------------------------------------
_INTERNAL_KEYS = {"_seq", "_session_redeemed"}


def public(obj):
    """Return a copy of an entity dict with internal-only keys removed."""
    return {k: v for k, v in obj.items() if k not in _INTERNAL_KEYS}


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3; scaffold pagination_defaults limit=10/min=1/max=100,
# offset>=0). Out-of-bounds limit/offset -> ERR_INVALID_REQUEST.
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")


def paginate(items, args):
    """Sort by created_at ASC (PRD §2.3), apply limit/offset, return (page, meta).

    `items` is a list of entity dicts already filtered. `args` is request.args.
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = PAGE_LIMIT_DEFAULT if limit_raw is None else _parse_int_param(limit_raw, "limit")
    offset = PAGE_OFFSET_DEFAULT if offset_raw is None else _parse_int_param(offset_raw, "offset")

    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        raise err("ERR_INVALID_REQUEST", "limit out of bounds (1..100)")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    ordered = sorted(items, key=lambda o: (o.get("created_at", ""), o.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [public(o) for o in page], meta
