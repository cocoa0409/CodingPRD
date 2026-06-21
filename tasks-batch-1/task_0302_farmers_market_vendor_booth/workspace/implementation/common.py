"""Shared helpers: common fields, pagination, type/bound validation, rounding."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request

from db import db, new_id
from errors import err

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Common entity fields (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
def init_common(obj):
    ts = db.clock.now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Mutation bump: refresh updated_at and increment version by exactly 1."""
    obj["updated_at"] = db.clock.now_iso()
    obj["version"] += 1


# ---------------------------------------------------------------------------
# Rounding (PRD §2.7)
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def floor_div(numerator, denominator):
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return int(q)


# ---------------------------------------------------------------------------
# Request-field validation primitives (ERR_INVALID_REQUEST, priority 4)
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def req_str(body, name, allow_empty=False):
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    if not allow_empty and v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {name} must not be empty")
    return v


def req_int(body, name):
    v = body.get(name)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_date(body, name):
    v = req_str(body, name)
    if not DATE_RE.match(v):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be YYYY-MM-DD")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a valid date")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at ASC (then _seq for stability), slice, build meta."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def created_sort(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
