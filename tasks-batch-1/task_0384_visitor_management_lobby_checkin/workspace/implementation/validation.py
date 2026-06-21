"""Shared body/field validation and pagination helpers.

Validation precedence (PRD §2.7):
  1 auth (401) -> 2 rbac (403) -> 3 existence (404) -> 4 well-formedness (422)
  -> 5 OCC (412) -> 6 state (409) -> 7+ business rules.
Routes call these helpers in that order.
"""
from flask import request

import errors

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the parsed JSON body as a dict (or {} when absent/empty)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return data


def invalid(message):
    return errors.ApiError(errors.ERR_INVALID_REQUEST, 422, message)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid("Field '%s' is required and must be a non-empty string" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid("Field '%s' must be a non-empty string when provided" % field)
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid("Field '%s' is required and must be an integer" % field)
    if minimum is not None and val < minimum:
        raise invalid("Field '%s' must be >= %s" % (field, minimum))
    return val


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise invalid("Field '%s' must be a boolean" % field)
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise invalid("Field '%s' must be one of %s" % (field, sorted(allowed)))
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise invalid("Field '%s' must be one of %s" % (field, sorted(allowed)))
    return val


def require_datetime(body, field):
    import clock
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid("Field '%s' is required and must be an ISO 8601 datetime string" % field)
    parsed = clock.parse_iso(val)
    if parsed is None:
        raise invalid("Field '%s' must be a valid ISO 8601 datetime" % field)
    return parsed


def optional_datetime(body, field):
    import clock
    if field not in body or body.get(field) is None:
        return None
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid("Field '%s' must be an ISO 8601 datetime string when provided" % field)
    parsed = clock.parse_iso(val)
    if parsed is None:
        raise invalid("Field '%s' must be a valid ISO 8601 datetime" % field)
    return parsed


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Bad values -> 422."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise invalid("limit must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ASC (tie-break id) and slice (PRD §2.3)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
