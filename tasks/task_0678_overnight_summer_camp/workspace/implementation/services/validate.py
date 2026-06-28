"""Request-shape validation helpers (ERR_INVALID_REQUEST, 400).

These are the lowest-precedence checks (PRD §3.10): required fields present and
well-typed, valid enum members, positive amounts where required. They are run
after the higher-precedence auth/existence/state/business checks unless the
field is needed earlier to resolve a reference.
"""
import db
from errors import ApiError
import errors


def bad_request(message="Invalid request."):
    return ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise bad_request(f"'{field}' must be a non-empty string.")
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise bad_request(f"'{field}' must be an integer.")
    return val


def optional_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise bad_request(f"'{field}' must be an integer.")
    return val


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise bad_request(f"'{field}' must be a boolean.")
    return val


def optional_str(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        raise bad_request(f"'{field}' must be a string.")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise bad_request(f"'{field}' must be one of {sorted(allowed)}.")
    return val


def require_positive_int(body, field):
    val = require_int(body, field)
    if val <= 0:
        raise bad_request(f"'{field}' must be a positive integer.")
    return val


def require_nonneg_int(body, field):
    val = require_int(body, field)
    if val < 0:
        raise bad_request(f"'{field}' must be a non-negative integer.")
    return val


def require_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise bad_request(f"'{field}' must be an ISO 8601 datetime string.")
    dt = db.parse_iso(val)
    if dt is None:
        raise bad_request(f"'{field}' must be a valid ISO 8601 datetime.")
    return dt
