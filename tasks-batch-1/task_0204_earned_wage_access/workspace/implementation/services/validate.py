"""Request validation helpers.

ERR_INVALID_REQUEST (400) for: missing required field, wrong type, enum out of
range, numeric out of declared bounds (PRD §2.11 priority 5).

Pagination per PRD §2.3: limit default 10, min 1, max 100; offset default 0.
An out-of-range limit/offset query param is treated as ERR_INVALID_REQUEST.
"""
import errors
from timeutil import parse_iso8601


def get_body():
    from flask import request
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Body must be a JSON object")
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


def require_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    _check_bounds(field, val, minimum, maximum)
    return val


def optional_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    _check_bounds(field, val, minimum, maximum)
    return val


def require_number(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    _check_bounds(field, val, minimum, maximum)
    return val


def optional_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    _check_bounds(field, val, minimum, maximum)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def require_datetime(body, field):
    val = require_str(body, field)
    try:
        return parse_iso8601(val)
    except Exception:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")


def _check_bounds(field, val, minimum, maximum):
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (PRD §2.3) using _seq for a stable total order."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
