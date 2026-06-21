"""Shared request-handling helpers: body parsing, validation primitives,
pagination, list filtering, and FK existence resolution.
"""
from flask import request

import calc
import db
from errors import err

# Map of FK body-field name -> the collection it must resolve in.
FK_COLLECTIONS = {
    "hotel_id": db.hotels,
    "guest_id": db.guests,
    "rate_plan_id": db.rate_plans,
    "room_type_id": db.room_types,
    "group_block_id": db.group_blocks,
    "room_id": db.rooms,
    "folio_id": db.folios,
    "corporate_account_id": db.corporate_accounts,
}


def get_json_body():
    """Parse the JSON body; return {} when absent. Malformed JSON -> ERR_INVALID_REQUEST."""
    if request.method == "GET":
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for %s" % field)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field, min_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %s out of range" % field)
    return v


def require_date(body, field):
    v = body.get(field)
    if calc.parse_date(v) is None:
        raise err("ERR_INVALID_REQUEST", "Field %s must be a valid YYYY-MM-DD date" % field)
    return v


def resolve_fk(body, field, optional=False):
    """Resolve a body FK against its collection. Missing existing -> ERR_REFERENCE_NOT_FOUND.

    Returns the resolved record, or None when optional and absent.
    """
    if field not in body or body[field] is None:
        if optional:
            return None
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    coll = FK_COLLECTIONS[field]
    rec = coll.get(body[field])
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced %s does not exist" % field)
    return rec


def get_or_404(collection, resource_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % resource_id)
    return rec


# ----------------------------------------------------------------------------
# Pagination + list filtering (PRD §2.3, §2.5)
# ----------------------------------------------------------------------------
def parse_pagination():
    """Read limit/offset query params with defaults; out-of-bounds -> ERR_PAGINATION_INVALID."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of bounds (1..100)")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset


def filter_and_paginate(collection, serializer, filters):
    """Apply equality filters, sort by created_at (ascending, _seq tiebreak), paginate.

    `filters` maps a stored-field name -> the query-param value (or None to skip).
    """
    limit, offset = parse_pagination()
    items = list(collection.values())
    for field, value in filters.items():
        if value is not None:
            items = [it for it in items if it.get(field) == value]
    items.sort(key=lambda it: (it["created_at"], it["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return [serializer(it) for it in page], limit, offset, total


def qparam(name):
    return request.args.get(name)
