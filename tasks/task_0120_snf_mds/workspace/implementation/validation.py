"""Request-body field validation and pagination parsing (PRD §2.3, §2.7 step 4).

All field-shape failures raise ERR_INVALID_REQUEST (422). Pagination out-of-range
also raises ERR_INVALID_REQUEST (the PRD defines limit min 1 / max 100; out of
range is a malformed request).
"""
import errors
from clock import parse_iso


def get_body():
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    from flask import request
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            # An empty body is acceptable for transitions with no required input;
            # represent as empty dict so required-field checks fire correctly.
            if request.data and request.data.strip():
                raise errors.err(errors.ERR_INVALID_REQUEST, "malformed JSON body")
            return {}
        if not isinstance(data, dict):
            raise errors.err(errors.ERR_INVALID_REQUEST, "body must be a JSON object")
        return data
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "missing required field: %s" % field)
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be a non-empty string" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "field %s must be one of %s" % (field, sorted(allowed)))
    return value


def as_int(value, field, minimum=None, maximum=None):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be <= %s" % (field, maximum))
    return value


def as_number(value, field, gt=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be a number" % field)
    if gt is not None and not (value > gt):
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be > %s" % (field, gt))
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be a boolean" % field)
    return value


def as_datetime(value, field):
    try:
        return parse_iso(value)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "field %s must be an ISO8601 datetime" % field)


def pagination(args):
    """Parse limit/offset query params (PRD §2.3). Returns (limit, offset)."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by creation order, apply offset/limit, return (page, total_count)."""
    ordered = sorted(rows, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
