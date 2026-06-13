"""Shared request helpers: body parsing, pagination, lookups, list output.

Validation ordering and pagination rules per PRD 2.3, 2.5, 2.6.
"""
from flask import request

import db
from errors import ApiError
from response import array_response, object_response


def get_json_body():
    """Return the parsed JSON body, or {} when absent. Malformed JSON -> 400."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def parse_pagination():
    """Parse limit/offset query params with defaults & bounds (PRD 2.3).

    limit default 10, min 1, max 100. offset default 0, min 0.
    Out of range -> ERR_INVALID_PAGINATION (400).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")

    return limit, offset


def paginated_list(items, serialize):
    """Sort by created_at asc (PRD 2.3), paginate, return an array envelope.

    Stable secondary sort on the monotonic _seq guards against ties when several
    resources share the same logical-clock created_at.
    """
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([serialize(r) for r in page], limit, offset, total)


def obj(resource, serialize, status=200):
    return object_response(serialize(resource), status)


# --- existence lookups (raise ERR_NOT_FOUND for path params) --- #
def must_get(collection, resource_id):
    r = collection.get(resource_id)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found.")
    return r


# --- body field validation helpers --- #
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {f}.")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    return v


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field {field} must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"Field {field} must be one of {sorted(allowed)}.")
    return v
