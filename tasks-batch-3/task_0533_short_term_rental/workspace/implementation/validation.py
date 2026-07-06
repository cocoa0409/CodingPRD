"""Request body parsing / validation helpers (raise ERR_INVALID_REQUEST 400)."""
from flask import request

import errors
from errors import err


def get_body():
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = {}
    if data is None:
        # Body present but not valid JSON, or explicitly null
        raise err(errors.ERR_INVALID_REQUEST, "Invalid JSON body")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require_str(body, field, allow_empty=False):
    if field not in body:
        raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    if not allow_empty and v == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must not be empty")
    return v


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} above maximum {maximum}")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return v


def opt_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit out of range [1,100]")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
