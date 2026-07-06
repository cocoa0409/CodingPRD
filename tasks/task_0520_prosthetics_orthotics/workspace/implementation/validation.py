"""Request-body validation + pagination helpers (PRD §2.3, §3.10).

ERR_INVALID_REQUEST: missing required field, bad enum value, out-of-range int.
"""
from flask import request

from errors import ApiError


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none/invalid)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string." % field)
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def require_int(body, field):
    val = body.get(field)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer." % field)
    return val


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return val


def parse_pagination():
    """Parse limit/offset query params. limit default 10, min 1, max 100;
    offset default 0, min 0. Bad values -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order, apply offset/limit, return (page, total)."""
    ordered = sorted(items, key=lambda e: e.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def lookup(store, rid):
    """Fetch by id or raise ERR_RESOURCE_NOT_FOUND."""
    ent = store.get(rid)
    if ent is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Resource '%s' not found." % rid)
    return ent
