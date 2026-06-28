"""Request body / query parsing helpers (PRD 2.3, validation priority 17).

Pagination defaults: limit default 10, min 1, max 100; offset default 0.
Malformed pagination or body fields -> ERR_INVALID_REQUEST (400).
"""

from errors import err

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def parse_pagination(args):
    """Parse limit/offset from query args (PRD 2.3)."""
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT

    if "limit" in args and args.get("limit") is not None and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if str(raw).strip() != str(limit):
            # reject things like "10.5" or "10abc"
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise err("ERR_INVALID_REQUEST", "limit out of range")

    if "offset" in args and args.get("offset") is not None and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if str(raw).strip() != str(offset):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative")

    return limit, offset


def get_body():
    """Return the JSON body as a dict, or empty dict when absent."""
    from flask import request
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"{field} is required and must be a non-empty string")
    return val


def optional_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return val


def optional_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return val


def require_number(body, field, positive=False):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} is required and must be a number")
    if positive and val <= 0:
        raise err("ERR_INVALID_REQUEST", f"{field} must be positive")
    return val


def optional_number(body, field, default=None, positive=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if positive and val <= 0:
        raise err("ERR_INVALID_REQUEST", f"{field} must be positive")
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} is required and must be an integer")
    return val


def optional_int(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}")
    return val
