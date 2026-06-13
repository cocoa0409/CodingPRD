"""Body parsing and field-level validation helpers (PRD §2.9).

Malformed bodies — missing required field, wrong type, or out-of-range value —
are rejected with ERR_VALIDATION (HTTP 400).
"""
from flask import request

import errors


def get_json_body():
    """Parse the request JSON body. Missing/invalid JSON yields {}.

    A body that is present but not a JSON object is a malformed body.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.err(errors.ERR_VALIDATION, "Malformed JSON body")
    if data is None:
        # Either empty body or unparseable. Treat empty as {}.
        if request.data and request.data.strip():
            raise errors.err(errors.ERR_VALIDATION, "Malformed JSON body")
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be a string" % field)
    return val


def require_int(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be an integer" % field)
    return val


def opt_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be an integer" % field)
    return val


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be a boolean" % field)
    return val


def opt_str_array(body, field, default):
    if field not in body or body[field] is None:
        return list(default)
    val = body[field]
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise errors.err(errors.ERR_VALIDATION, "Field %s must be an array of strings" % field)
    return list(val)


def in_range(field, val, lo, hi):
    if val < lo or val > hi:
        raise errors.err(errors.ERR_VALIDATION,
                         "Field %s out of range [%s, %s]" % (field, lo, hi))
    return val


def in_set(field, val, allowed):
    if val not in allowed:
        raise errors.err(errors.ERR_VALIDATION,
                         "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def parse_pagination():
    """Read limit/offset query params (PRD §2.3). Out-of-range -> ERR_VALIDATION."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise errors.err(errors.ERR_VALIDATION, "limit must be in [1, 100]")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset_v < 0:
            raise errors.err(errors.ERR_VALIDATION, "offset must be >= 0")
    return limit_v, offset_v
