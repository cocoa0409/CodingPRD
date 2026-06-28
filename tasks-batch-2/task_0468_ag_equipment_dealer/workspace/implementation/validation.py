"""Input validation, typed field extraction, pagination, serialization.

Validation precedence (PRD §3.9): auth -> forbidden -> not_found -> invalid_request
(field presence/type/enum/numeric) -> duplicate_key -> invalid_state -> occ ->
business rules. The routes call these helpers in the right order.
"""
from flask import request

import errors
from errors import err


def get_json():
    """Return the request JSON body as a dict (empty dict if none)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a non-empty string.")
    return val


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string.")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST,
                  f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST,
                  f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def _is_int(val):
    # bool is a subclass of int — reject it as an integer field
    return isinstance(val, int) and not isinstance(val, bool)


def require_int(body, field, minimum=None, gt=None):
    val = body.get(field)
    if not _is_int(val):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer.")
    _check_numeric_bounds(field, val, minimum, gt)
    return val


def optional_int(body, field, default=0, minimum=None, gt=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_int(val):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be an integer.")
    _check_numeric_bounds(field, val, minimum, gt)
    return val


def require_number(body, field, minimum=None, gt=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a number.")
    _check_numeric_bounds(field, val, minimum, gt)
    return val


def optional_number(body, field, default=0, minimum=None, gt=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a number.")
    _check_numeric_bounds(field, val, minimum, gt)
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean.")
    return val


def _check_numeric_bounds(field, val, minimum, gt):
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be >= {minimum}.")
    if gt is not None and val <= gt:
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be > {gt}.")


def optional_fk(body, field):
    """An optional foreign-key string (may be omitted or explicitly null)."""
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string id.")
    return val


def require_fk(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field '{field}' must be a string id.")
    return val


# --- pagination (PRD §2.3) ----------------------------------------------------
def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """items is the full sorted list; returns the page window."""
    total = len(items)
    window = items[offset:offset + limit]
    return window, total
