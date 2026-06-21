"""Body / query-param well-formedness helpers (validation priority 5, §1.4).

All raise ERR_INVALID_REQUEST (422) on malformed input.
"""
from errors import err
from util import parse_dt


def get_body(req):
    """Parse JSON body; tolerate empty body for endpoints with no input."""
    if req.content_length in (None, 0):
        return {}
    try:
        data = req.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    return body[field]


def require_str(body, field, non_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    if non_empty and v.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-empty.")
    return v


def require_int(body, field, minimum=None, maximum=None, allowed=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum.")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum.")
    if allowed is not None and v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} not in allowed values.")
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def require_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def require_dt(body, field):
    raw = require(body, field)
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime.")
    return dt


def opt_int(body, field, default=None, minimum=None, maximum=None, allowed=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum, allowed)


def parse_pagination(args):
    """limit default 10 in [1,100]; offset default 0, >= 0. -> ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be in [1, 100].")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    return records[offset:offset + limit]
