"""Body-conformance and pagination validation (PRD §2.3, §2.5).

Validation precedence (scaffold §1.4): auth -> existence -> body conformance.
These helpers handle body conformance (ERR_INVALID_REQUEST, 422) and pagination
(ERR_VALIDATION_PAGINATION, 422). Existence (404) is checked by callers BEFORE
body conformance per the left-to-right id-resolution rule.
"""
from flask import request

from errors import invalid_request, invalid_pagination


def get_body():
    """Return the JSON body as a dict; reject non-object bodies."""
    if request.method in ("GET", "DELETE"):
        # body, if any, is ignored
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    data = request.get_json(silent=True)
    if data is None:
        # Allow empty body for transition endpoints that take no input.
        if request.content_length in (None, 0):
            return {}
        raise invalid_request("Request body must be a JSON object")
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request("Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise invalid_request("Field %s must be a non-empty string" % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise invalid_request("Field %s must be a string" % field)
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise invalid_request("Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise invalid_request("Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int_nonneg(body, field):
    val = require(body, field)
    if not _is_int(val) or val < 0:
        raise invalid_request("Field %s must be an integer >= 0" % field)
    return val


def opt_int_nonneg(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_int(val) or val < 0:
        raise invalid_request("Field %s must be an integer >= 0" % field)
    return val


def require_int_min(body, field, minimum):
    val = require(body, field)
    if not _is_int(val) or val < minimum:
        raise invalid_request("Field %s must be an integer >= %d" % (field, minimum))
    return val


def opt_int_min(body, field, minimum, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_int(val) or val < minimum:
        raise invalid_request("Field %s must be an integer >= %d" % (field, minimum))
    return val


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise invalid_request("Field %s must be a boolean" % field)
    return val


def require_bool(body, field):
    val = require(body, field)
    if not isinstance(val, bool):
        raise invalid_request("Field %s must be a boolean" % field)
    return val


def opt_fraction(body, field, default=0):
    """0..1 inclusive fractional discount factor."""
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise invalid_request("Field %s must be a number in [0,1]" % field)
    if val < 0 or val > 1:
        raise invalid_request("Field %s must be in [0,1]" % field)
    return val


def pagination():
    """Parse limit/offset. Defaults limit=10, offset=0. Range 1<=limit<=100, offset>=0."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise invalid_pagination("limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise invalid_pagination("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_pagination("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_pagination("offset must be >= 0")
    return limit, offset
