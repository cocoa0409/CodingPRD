"""Request body / query-param parsing and well-formedness validation.

Body well-formedness failures map to ERR_INVALID_REQUEST (priority 6).
Pagination parsing per PRD 2.3.
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST


def get_json_body():
    """Return the parsed JSON object body, defaulting to {} for empty bodies.

    A malformed JSON payload or a non-object top level is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {f}")


def req_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"field {key} must be a string")
    return val


def req_int(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {key}")
        return default
    val = body[key]
    # bool is a subclass of int — reject it explicitly
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"field {key} must be an integer")
    return val


def req_number(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {key}")
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"field {key} must be a number")
    return val


def req_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"field {key} must be a boolean")
    return val


def req_enum(body, key, members, required=True, default=None):
    val = req_str(body, key, required=required, default=default)
    if val is None:
        return None
    if val not in members:
        raise err(ERR_INVALID_REQUEST, f"field {key} must be one of {sorted(members)}")
    return val


def req_str_list(body, key, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {key}")
        return list(default) if default is not None else []
    val = body[key]
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise err(ERR_INVALID_REQUEST, f"field {key} must be an array of strings")
    return val


def parse_pagination():
    """Return (limit, offset) per PRD 2.3: limit default 10 (1..100), offset default 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Slice a fully-sorted list; return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
