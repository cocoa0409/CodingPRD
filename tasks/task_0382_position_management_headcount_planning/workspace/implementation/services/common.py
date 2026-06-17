"""Shared request helpers: body parsing, validation primitives, entity lookup,
version/timestamp bumping, pagination (PRD §2.3, §2.4, §2.5)."""
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import err
from util import new_id, iso_now, now_utc


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON ->
    ERR_INVALID_REQUEST (422)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "missing required field: " + f)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "field must be a non-empty string: " + field)
    return v


def require_int(body, field, min_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "field must be an integer: " + field)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "field below minimum: " + field)
    return v


def require_enum(body, field, members):
    v = body.get(field)
    if v not in members:
        raise err("ERR_INVALID_REQUEST", "field must be one of {}: {}".format(sorted(members), field))
    return v


def validate_fte(value):
    """fte must be > 0 and <= 1.0 with at most two decimal places
    (PRD §2.5, §3.2). Returns the value as a float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "fte must be a number")
    d = Decimal(str(value))
    if d <= 0 or d > Decimal("1.0"):
        raise err("ERR_INVALID_REQUEST", "fte must be in (0, 1.0]")
    if -d.as_tuple().exponent > 2:
        raise err("ERR_INVALID_REQUEST", "fte may have at most two decimals")
    return float(d)


def validate_nonneg_fte(value):
    """A planned_fte-style value: >= 0 with at most two decimals (PRD §3.9)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "value must be a number")
    d = Decimal(str(value))
    if d < 0:
        raise err("ERR_INVALID_REQUEST", "value must be >= 0")
    if -d.as_tuple().exponent > 2:
        raise err("ERR_INVALID_REQUEST", "value may have at most two decimals")
    return float(d)


# ---------------------------------------------------------------------------
# Entity lookup (existence — priority 3, ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def fetch(collection, entity_id):
    rec = collection.get(entity_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return rec


# ---------------------------------------------------------------------------
# Record lifecycle helpers
# ---------------------------------------------------------------------------
def base_common_fields():
    """id, created_at, updated_at, version=1 + monotonic _seq (PRD §2.4)."""
    ts = iso_now(now_utc())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def base_immutable_fields():
    """id, created_at only (Grade, BudgetAdjustment — PRD §2.4)."""
    ts = iso_now(now_utc())
    return {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }


def bump(rec):
    """Advance version by 1 and refresh updated_at (PRD §2.4, §2.10)."""
    rec["version"] += 1
    rec["updated_at"] = iso_now(now_utc())


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Returns (limit, offset). Defaults limit=10 (min 1, max 100), offset=0
    (min 0). Out-of-range / malformed -> ERR_INVALID_REQUEST (422)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(records):
    """Sort by created_at ascending (PRD §2.3), then apply limit/offset.
    Ties broken by insertion sequence for stable ordering. Returns
    (page, limit, offset, total_count)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
