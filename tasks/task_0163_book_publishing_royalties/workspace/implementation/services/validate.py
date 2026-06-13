"""Input parsing + well-formedness + numeric range validation.

Priority order (PRD §2.10): after auth/authz/existence, the system checks
well-formedness (ERR_INVALID_REQUEST) and then range (ERR_VALIDATION_RANGE).
We surface ERR_INVALID_REQUEST for missing/wrong-type/bad-enum, and
ERR_VALIDATION_RANGE for an in-type-but-out-of-range numeric value.
"""
from flask import request

import errors


def get_body():
    """Return the parsed JSON body as a dict. Absent body => {} (well-formed empty)."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        # Body provided but unparseable / not JSON object.
        if request.data:
            raise errors.invalid_request("Request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_present(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    return body[field]


def as_string(value, field):
    if not isinstance(value, str):
        raise errors.invalid_request("Field %s must be a string." % field)
    return value


def req_string(body, field):
    v = require_present(body, field)
    return as_string(v, field)


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return as_string(body[field], field)


def _check_int(value, field):
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    return value


def req_int(body, field):
    v = require_present(body, field)
    return _check_int(v, field)


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return _check_int(body[field], field)


def _check_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % field)
    return value


def req_number(body, field):
    v = require_present(body, field)
    return _check_number(v, field)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return _check_number(body[field], field)


def req_enum(body, field, allowed):
    v = req_string(body, field)
    if v not in allowed:
        raise errors.invalid_request("Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = as_string(body[field], field)
    if v not in allowed:
        raise errors.invalid_request("Field %s must be one of %s." % (field, sorted(allowed)))
    return v


# ---- Range checks (ERR_VALIDATION_RANGE, HTTP 422) ----

def range_pct_closed(value, field):
    """Percentage in closed [0, 1]."""
    if not (0 <= value <= 1):
        raise errors.validation_range("%s must be within [0, 1]." % field)
    return value


def range_pct_open_low(value, field):
    """Percentage in (0, 1] — strictly above 0, at most 1."""
    if not (0 < value <= 1):
        raise errors.validation_range("%s must be greater than 0 and at most 1." % field)
    return value


def range_ge(value, field, bound):
    if not (value >= bound):
        raise errors.validation_range("%s must be >= %s." % (field, bound))
    return value


def range_gt(value, field, bound):
    if not (value > bound):
        raise errors.validation_range("%s must be > %s." % (field, bound))
    return value


# ---- Pagination (PRD §2.3) ----

def pagination():
    """Parse limit/offset query params with defaults; range-validate them."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation_range("limit must be between 1 and 100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.validation_range("offset must be >= 0.")
    return limit, offset
