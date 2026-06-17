"""Body parsing, generic input validation, pagination (PRD §2.3, §2.11)."""
from flask import request

from errors import err


def get_body():
    """Return the JSON body as a dict, or {} when absent.

    A malformed JSON body is treated as a validation error.
    """
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_string(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_VALIDATION", "Missing required field: " + field)
    value = body[field]
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "Field must be a string: " + field)
    if not allow_empty and value == "":
        raise err("ERR_VALIDATION", "Field must not be empty: " + field)
    return value


def require_int(body, field, minimum=None):
    if field not in body:
        raise err("ERR_VALIDATION", "Missing required field: " + field)
    value = body[field]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", "Field must be an integer: " + field)
    if minimum is not None and value < minimum:
        raise err("ERR_VALIDATION", "Field below minimum: " + field)
    return value


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum)


def require_bool(body, field):
    if field not in body:
        raise err("ERR_VALIDATION", "Missing required field: " + field)
    value = body[field]
    if not isinstance(value, bool):
        raise err("ERR_VALIDATION", "Field must be a boolean: " + field)
    return value


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "Field must be a string: " + field)
    return value


def require_enum(body, field, allowed):
    value = require_string(body, field)
    if value not in allowed:
        raise err("ERR_VALIDATION", "Invalid enum value for field: " + field)
    return value


def require_datetime(body, field):
    """Datetimes are stored verbatim as ISO 8601 strings (PRD §2.10/§3.2)."""
    return require_string(body, field)


def optional_array(body, field, default):
    if field not in body or body[field] is None:
        return list(default)
    value = body[field]
    if not isinstance(value, list):
        raise err("ERR_VALIDATION", "Field must be an array: " + field)
    return value


def parse_pagination():
    """limit default 10 (min 1 max 100); offset default 0 (PRD §2.3)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at ASC (then _seq tie-break), then page (PRD §2.3)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, limit, offset, total
