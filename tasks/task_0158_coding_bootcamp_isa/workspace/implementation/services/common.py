"""Shared helpers: body parsing, pagination, list-and-paginate, field validation."""
from flask import request

import errors
from db import db


def get_json_body():
    """Parse JSON body; tolerate empty body for action endpoints."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def parse_pagination():
    """limit/offset with PRD §2.3 bounds. Out-of-range -> ERR_VALIDATION (422)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")

    if limit < 1 or limit > 100:
        raise errors.validation("limit must be between 1 and 100")
    if offset < 0:
        raise errors.validation("offset must be >= 0")
    return limit, offset


def sort_by_created(rows):
    """Default list ordering: created_at ascending (PRD §2.3), seq tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    has_more = offset + limit < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, pagination


# --- field validation helpers --------------------------------------------------

def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def as_int(body, name, required=True, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{name} must be an integer")
    if min_value is not None and val < min_value:
        raise errors.invalid_request(f"{name} must be >= {min_value}")
    if max_value is not None and val > max_value:
        raise errors.invalid_request(f"{name} must be <= {max_value}")
    return val


def as_number(body, name, required=True, gt=None, ge=None, le=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"{name} must be a number")
    if gt is not None and not (val > gt):
        raise errors.invalid_request(f"{name} must be > {gt}")
    if ge is not None and not (val >= ge):
        raise errors.invalid_request(f"{name} must be >= {ge}")
    if le is not None and not (val <= le):
        raise errors.invalid_request(f"{name} must be <= {le}")
    return val


def as_enum(body, name, choices, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    val = body[name]
    if val not in choices:
        raise errors.invalid_request(f"{name} must be one of {sorted(choices)}")
    return val


def as_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request(f"{name} must be a string")
    return val


def as_bool(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"{name} must be a boolean")
    return val


def lookup(collection, _id):
    """Existence check returning the row or raising ERR_NOT_FOUND (404)."""
    row = collection.get(_id)
    if row is None:
        raise errors.not_found(f"Resource not found: {_id}")
    return row
