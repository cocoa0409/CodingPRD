"""Request-body well-formedness helpers (PRD §2.8, validation priority 4)."""
from flask import request

from errors import invalid_request


def get_json_body():
    """Return the JSON body as a dict, or {} when absent/empty.

    A malformed (non-JSON) body for a write yields ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise invalid_request(f"Field {field} must be a non-empty string")
    return val


def require_enum(body, field, choices):
    val = require(body, field)
    if val not in choices:
        raise invalid_request(f"Field {field} must be one of {sorted(choices)}")
    return val


def opt_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in choices:
        raise invalid_request(f"Field {field} must be one of {sorted(choices)}")
    return val


def require_number(body, field, minimum=None, maximum=None, gt=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    _check_bounds(field, val, minimum, maximum, gt)
    return val


def opt_number(body, field, default, minimum=None, maximum=None, gt=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    _check_bounds(field, val, minimum, maximum, gt)
    return val


def require_int(body, field, minimum=None, maximum=None, gt=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request(f"Field {field} must be an integer")
    _check_bounds(field, val, minimum, maximum, gt)
    return val


def opt_int(body, field, default, minimum=None, maximum=None, gt=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request(f"Field {field} must be an integer")
    _check_bounds(field, val, minimum, maximum, gt)
    return val


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise invalid_request(f"Field {field} must be a boolean")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise invalid_request(f"Field {field} must be a string")
    return val


def fk_value(body, field, required=True):
    """Read a foreign-key value from the body for existence checking.

    A required FK that is absent/null/non-string fails priority-4 well-formedness
    (ERR_INVALID_REQUEST); an optional FK that is absent returns None. When the
    value is present, it is returned for a priority-3 existence check by the
    caller. (PRD §2.7/§2.8: present-but-unresolvable FK -> 404; absent required
    field -> 422.)
    """
    if field not in body or body[field] is None:
        if required:
            raise invalid_request(f"Missing required field: {field}")
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise invalid_request(f"Field {field} must be a non-empty string")
    return val


def _check_bounds(field, val, minimum, maximum, gt):
    if gt is not None and not (val > gt):
        raise invalid_request(f"Field {field} must be greater than {gt}")
    if minimum is not None and val < minimum:
        raise invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise invalid_request(f"Field {field} must be <= {maximum}")


# --- pagination (PRD §2.3) ---
def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at asc (tie-break on insertion seq), then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
