"""Request-body validation (tier 1), existence checks (tier 4), pagination (2.3)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import is_valid_iso_datetime, parse_datetime

_UNSET = object()


def get_body():
    """Tier 1: the body parses as JSON and is an object. Empty body -> {}.

    Undeclared or read-only payload fields are ignored by the field helpers
    below (PRD 2.6 tier 1).
    """
    raw = request.get_data(cache=True)
    if raw and raw.strip():
        body = request.get_json(silent=True)
        if body is None:
            raise_error(ERR_INVALID_REQUEST, "request body is not valid JSON")
        if not isinstance(body, dict):
            raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return body
    return {}


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def _check_int(v, field, minimum, maximum):
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    return _check_int(v, field, minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def opt_nullable_int(body, field, minimum=None):
    """PATCH helper: absent -> _UNSET (unchanged); null -> None; else int."""
    if field not in body:
        return _UNSET
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"invalid integer field: {field}")
    return _check_int(v, field, minimum, None)


def req_num(body, field, exclusive_min=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    v = float(v)
    if exclusive_min is not None and not (v > exclusive_min):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > {exclusive_min}")
    return v


def opt_num(body, field, default=None, exclusive_min=None):
    if field not in body or body.get(field) is None:
        return default
    return req_num(body, field, exclusive_min=exclusive_min)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_dt(body, field):
    v = req_str(body, field)
    if not is_valid_iso_datetime(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")
    return parse_datetime(v)


def opt_dt(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_dt(body, field)


def get_pagination():
    """PRD 2.3: limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
        offset = int(args.get("offset", "0"))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "invalid pagination parameters")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def require_path(collection, rid):
    """Tier 4: path identifier existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_fk(collection, rid, field):
    """Tier 4: body foreign-key existence (left-to-right call order)."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
