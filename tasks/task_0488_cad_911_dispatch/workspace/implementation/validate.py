"""Request-body well-formedness validation (PRD §2.6 priority 5, ERR_INVALID_REQUEST).

These helpers run AFTER auth, path existence, and FK existence (per the fixed
precedence in PRD §2.6). They check: required fields present, enums legal,
integers in range, ANI exactly 10 digits, grids in 0..1000 inclusive.
"""
from errors import err, ERR_INVALID_REQUEST


def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}.")
    return body[field]


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Invalid value for {field}: {val!r}.")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Invalid value for {field}: {val!r}.")
    return val


def require_string(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string.")
    return val


def _check_int(val, field, lo=None, hi=None):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if lo is not None and val < lo:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {lo}.")
    if hi is not None and val > hi:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be <= {hi}.")
    return val


def require_int(body, field, lo=None, hi=None):
    val = require(body, field)
    return _check_int(val, field, lo, hi)


def optional_int(body, field, lo=None, hi=None, default=None):
    if field not in body or body[field] is None:
        return default
    return _check_int(body[field], field, lo, hi)


def require_grid(body, field):
    return require_int(body, field, lo=0, hi=1000)


def optional_grid(body, field, default=None):
    return optional_int(body, field, lo=0, hi=1000, default=default)


def require_ani(body, field="ani"):
    val = require(body, field)
    if not isinstance(val, str) or len(val) != 10 or not val.isdigit():
        raise err(ERR_INVALID_REQUEST, "ani must be exactly 10 digits.")
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean.")
    return val
