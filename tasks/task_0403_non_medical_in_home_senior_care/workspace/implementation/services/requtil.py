"""Request body parsing, well-formedness, and pagination helpers (PRD §2.3, §2.7)."""
from flask import request

import errors
from clock import parse_iso8601
from errors import ApiError


def get_body():
    """Return the JSON body as a dict. Non-object / unparseable -> {}.

    A malformed JSON body that isn't an object is treated as empty so the
    missing-required-field checks fire ERR_INVALID_REQUEST consistently.
    """
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return {}
    return data


def invalid(message="Invalid request"):
    return ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise invalid("Missing or invalid field: %s" % field)
    return v


def require_present(body, field):
    if field not in body or body[field] is None:
        raise invalid("Missing required field: %s" % field)
    return body[field]


def require_number(body, field):
    if field not in body or body[field] is None:
        raise invalid("Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("Field %s must be a number" % field)
    return v


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("Field %s must be a number" % field)
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Field %s must be an integer" % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise invalid("Field %s must be a boolean" % field)
    return v


def require_enum(body, field, choices):
    v = require_present(body, field)
    if v not in choices:
        raise invalid("Field %s must be one of %s" % (field, sorted(choices)))
    return v


def require_datetime(body, field):
    require_present(body, field)
    dt = parse_iso8601(body[field])
    if dt is None:
        raise invalid("Field %s must be an ISO 8601 datetime" % field)
    return dt


def pagination():
    """Parse limit/offset query params (PRD §2.3). limit default 10, min 1, max
    100; offset default 0. Out-of-range / malformed -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order ascending (PRD §2.3) and slice."""
    ordered = sorted(items, key=lambda o: o.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
