"""Shared helpers: pagination, body parsing, FK existence, enum/field validation."""
from flask import request

from db import db
from errors import ApiError
from response import array_response, object_response

# entity collection -> not-found error id
NOT_FOUND = {
    "host_sites": "ERR_HOST_SITE_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "machines": "ERR_MACHINE_NOT_FOUND",
    "slots": "ERR_SLOT_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "routes": "ERR_ROUTE_NOT_FOUND",
    "stops": "ERR_STOP_NOT_FOUND",
    "visits": "ERR_VISIT_NOT_FOUND",
    "sales": "ERR_SALE_NOT_FOUND",
    "statements": "ERR_STATEMENT_NOT_FOUND",
    "tickets": "ERR_TICKET_NOT_FOUND",
}


def get_or_404(collection_name, obj_id):
    coll = getattr(db, collection_name)
    obj = coll.get(obj_id)
    if obj is None:
        raise ApiError(NOT_FOUND[collection_name],
                       f"{collection_name[:-1]} not found")
    return obj


def get_json_body():
    """Parse JSON body. Reject malformed/non-object bodies with ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=False, silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed request body")
    if data is None:
        # empty body is allowed for action endpoints; treat as {}
        if not request.data:
            return {}
        raise ApiError("ERR_INVALID_REQUEST", "Malformed request body")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_int(body, field, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def require_number(body, field, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    return v


def require_enum(body, field, allowed, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Field {field} has invalid enum value: {v}")
    return v


def require_bool(body, field, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0). PRD 2.3."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(rows, serializer):
    """Sort by created_at asc (tie-break internal seq), paginate, envelope."""
    rows = sorted(rows, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(rows)
    limit, offset = parse_pagination()
    page = rows[offset:offset + limit]
    return array_response([serializer(o) for o in page], limit, offset, total)
