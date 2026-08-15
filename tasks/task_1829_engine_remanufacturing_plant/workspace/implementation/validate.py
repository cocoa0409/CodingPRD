"""Request-body well-formedness (validation priority 3) and pagination parsing.

Body rules: required fields present, no undeclared fields, enums within their
declared sets, types correct, numeric ranges respected, and end timestamps
strictly after start timestamps.  All violations yield ERR_VALIDATION (400).
"""

from flask import request

import clock as clockmod
from errors import ERR_VALIDATION, raise_error


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def check_allowed_fields(body, allowed):
    extra = [k for k in body if k not in allowed]
    if extra:
        raise_error(
            ERR_VALIDATION, "undeclared field(s): %s" % ", ".join(sorted(extra))
        )


def _bad(field, why="missing or invalid"):
    raise_error(ERR_VALIDATION, "%s: %s" % (why, field))


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        _bad(field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        _bad(field, "missing or not one of %s in" % sorted(allowed))
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "missing or not an integer")
    if minimum is not None and v < minimum:
        _bad(field, "below minimum %s" % minimum)
    if maximum is not None and v > maximum:
        _bad(field, "above maximum %s" % maximum)
    return v


def req_number(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field, "missing or not a number")
    if minimum is not None and v < minimum:
        _bad(field, "below minimum %s" % minimum)
    if maximum is not None and v > maximum:
        _bad(field, "above maximum %s" % maximum)
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        _bad(field, "missing or not a boolean")
    return v


def req_list(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, list):
        _bad(field, "missing or not an array")
    return v


def req_str_list(body, field):
    v = req_list(body, field)
    for item in v:
        if not isinstance(item, str) or item.strip() == "":
            _bad(field, "array entries must be non-empty strings")
    return v


def req_enum_list(body, field, allowed):
    v = req_list(body, field)
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            _bad(field, "array entries must be within %s" % sorted(allowed))
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v.strip() == "":
        _bad(field)
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, minimum=minimum, maximum=maximum)


def req_instant(body, field):
    """Caller-supplied ISO 8601 instant: returns (raw_string, parsed)."""
    raw = body.get(field)
    if raw is None or not isinstance(raw, str):
        _bad(field, "missing or not an ISO 8601 timestamp")
    parsed = clockmod.parse_instant(raw)
    if parsed is None:
        _bad(field, "not a well-formed ISO 8601 timestamp")
    return raw, parsed


def pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0 (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise_error(ERR_VALIDATION, "limit must be an integer within [1, 100]")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be within [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise_error(ERR_VALIDATION, "offset must be an integer >= 0")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def filter_enum(name, allowed):
    """Validate an optional enum-typed query filter against its declared set."""
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise_error(ERR_VALIDATION, "query filter %s must be within %s" % (name, sorted(allowed)))
    return v
