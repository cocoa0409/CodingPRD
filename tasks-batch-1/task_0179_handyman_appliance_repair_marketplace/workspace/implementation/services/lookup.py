"""Existence lookups (ERR_NOT_FOUND) and request-body validation helpers.

Body shape problems surface ERR_INVALID_REQUEST (400). Existence surfaces
ERR_NOT_FOUND (404). Per PRD §2.9 the per-route code calls the shape helpers
first (priority 1), then auth is enforced by the @require_role decorator before
the view body runs, then existence checks, then semantic/ownership/state/business
rules.
"""
from flask import request

from errors import ApiError


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource %s not found" % rid)
    return rec


def require_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_string(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return val


def require_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for %s: %r" % (field, val))
    return val


def require_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s below minimum %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s above maximum %s" % (field, maximum))
    return val


def require_number(body, field, required=True, default=None, minimum=None,
                   maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s below minimum %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s above maximum %s" % (field, maximum))
    return val


def require_bool(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return val


def require_string_array(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return list(default) if default is not None else []
    val = body[field]
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an array of strings" % field)
    return val


def require_datetime(body, field, required=True, default=None):
    from timeutil import parse_dt
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    try:
        return parse_dt(body[field])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % field)


# ---------------------------------------------------------------------------
# Pagination + sorting (PRD §2.3): default limit 10 (min 1, max 100), offset 0.
# ---------------------------------------------------------------------------
def paginate(query_args, items):
    total = len(items)
    limit = _pag_int(query_args.get("limit"), default=10, lo=1, hi=100)
    offset = _pag_int(query_args.get("offset"), default=0, lo=0, hi=None)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _pag_int(raw, default, lo, hi):
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    if val < lo:
        val = lo
    if hi is not None and val > hi:
        val = hi
    return val


def sorted_by_creation(records):
    """List endpoints sort by created_at ascending, tie-broken by creation seq
    (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
