"""Request body parsing / type validation helpers (ERR_INVALID_REQUEST, 400)."""
from flask import request

from errors import err


def get_body():
    """Return the JSON body as a dict, or {} for an empty body. A body that is
    present but not a JSON object is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field, allow_empty=False):
    val = require(body, field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    if not allow_empty and val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-empty." % field)
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return val


def require_number(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def require_enum(body, field, choices):
    val = require_str(body, field, allow_empty=True)
    if val not in choices:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(choices)))
    return val


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return val


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3. limit default 10, min 1,
    max 100; offset default 0. Bad values -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset
