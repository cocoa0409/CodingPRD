"""Request-body validation helpers (validation priority 4 — ERR_INVALID_REQUEST).

These run AFTER existence checks per PRD 2.9. Note: existence (priority 3) is
checked separately in each route before body well-formedness.
"""
import errors


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return val


def opt_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def require_str_id(body, field):
    """A foreign-key reference: must be a non-empty string."""
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a string id")
    return val


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0. (PRD 2.3)
    Out-of-range / malformed -> ERR_INVALID_REQUEST."""
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: list already sorted ascending by created_at. Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
