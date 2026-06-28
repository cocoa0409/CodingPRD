"""Shared helpers: common entity fields, input validation primitives,
pagination, money rounding."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import new_id, now_iso
from errors import err


# ---------------------------------------------------------------------------
# Common resource fields (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
def stamp_new(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version by one (any mutation, incl. computed)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.5): round-half-up to whole cents
# ---------------------------------------------------------------------------
def round_half_up(cents_times_rate):
    """Round a numeric value to the nearest whole cent, half away from zero."""
    d = Decimal(str(cents_times_rate))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(cents, rate):
    """round_half_up(cents * rate) using exact Decimal arithmetic."""
    return round_half_up(Decimal(cents) * Decimal(str(rate)))


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def as_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return val


def as_number(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return val


def as_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return val


def as_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in choices:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, choices))
    return val


def check_range(field, val, minimum=None, maximum=None, multiple_of=None):
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be <= %s" % (field, maximum))
    if multiple_of is not None and val % multiple_of != 0:
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a multiple of %s" % (field, multiple_of))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0 min 0.
# Sorted by created_at ascending unless stated otherwise.
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_val < 1:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be >= 1")
        if limit_val > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be <= 100")
    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_val < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit_val, offset_val


def paginate(items):
    """items must be pre-sorted. Returns (page_items, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(values):
    return sorted(values, key=lambda e: (e["created_at"], e["id"]))
