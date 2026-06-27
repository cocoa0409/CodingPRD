"""Request body parsing and field validation helpers.

These raise ERR_INVALID_REQUEST (400) for missing/ill-typed/out-of-set fields,
per validation priority 5 (PRD §3.9 ordering).
"""

from flask import request

from errors import err

# Read roles for GET endpoints: all five roles may read every resource (PRD §2.1).
ALL_ROLES = ["Petitioner", "CourtExaminer", "Judge", "Fiduciary", "CourtClerk"]


def get_json_body():
    """Return the parsed JSON object body, or {} when absent. Non-object -> 400."""
    if request.method == "GET":
        return {}
    raw = request.get_data(cache=True)
    if not raw or raw.strip() == b"":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_string(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    value = body[field]
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return value


def require_enum(body, field, allowed):
    value = require_string(body, field)
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return value


def require_int(body, field, minimum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    value = body[field]
    # Booleans are ints in Python; reject them explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    if exclusive_min is not None and value <= exclusive_min:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {exclusive_min}")
    return value


def optional_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return value


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return value


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Bad values -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (tie-break by _seq) then window by limit/offset."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
