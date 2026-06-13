"""Request body parsing and shared field validation."""
from flask import request

from errors import err


def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON ->
    ERR_INVALID_REQUEST (PRD §3.10).
    """
    if request.data is None or len(request.data) == 0:
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


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Missing or invalid field: %s" % field)
    return val


def require_enum(body, field, members):
    val = body.get(field)
    if val not in members:
        raise err("ERR_INVALID_REQUEST", "Invalid enum member for %s" % field)
    return val


def require_positive_amount(body, field="amount_cents"):
    """amount_cents must be a strictly positive integer -> ERR_INVALID_AMOUNT."""
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
        raise err("ERR_INVALID_AMOUNT", "%s must be strictly positive" % field)
    return val


def require_int(body, field):
    val = body.get(field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Missing or invalid integer field: %s" % field)
    return val


def optional_bool(body, field, default):
    val = body.get(field, default)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def pagination_params():
    """Parse limit/offset (PRD §2.3). limit default 10, min 1, max 100;
    offset default 0.
    """
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset
