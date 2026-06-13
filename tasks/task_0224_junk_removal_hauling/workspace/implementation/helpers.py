"""Request-parsing, pagination, and validation helpers shared across routes."""
from flask import request
import errors
from errors import err


def get_json_body():
    """Return the request JSON body as a dict, or {} if empty. ERR_INVALID_REQUEST if malformed."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but not parseable as JSON
        if request.get_data(cache=True):
            err(errors.ERR_INVALID_REQUEST, "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return value


def as_str(value, field):
    if not isinstance(value, str):
        err(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        err(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def pagination_params():
    """Parse limit/offset query params per PRD §2.3 (limit default 10, min 1, max 100;
    offset default 0, min 0). Invalid values -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sort_by_creation(items):
    """Ascending creation order via the monotonic _seq counter (PRD §2.3)."""
    return sorted(items, key=lambda o: o["_seq"])


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
