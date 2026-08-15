"""Request-body shape validation (tier 4), existence checks (tier 5), pagination."""
from datetime import date, datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def check_allowed(body, allowed_fields):
    """Tier 4: unknown fields are rejected (PRD 2.10)."""
    for key in body:
        if key not in allowed_fields:
            raise_error(ERR_INVALID_REQUEST, f"unknown field: {key}")


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


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def _check_int(v, field, positive, non_negative, minimum, maximum):
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def req_int(body, field, minimum=None, maximum=None, positive=False, non_negative=False):
    return _check_int(body.get(field), field, positive, non_negative, minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return _check_int(body.get(field), field, positive, non_negative, minimum, maximum)


def req_number(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, minimum=minimum, maximum=maximum)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def req_date(body, field):
    """Validate YYYY-MM-DD; returns the canonical ISO string."""
    v = req_str(body, field)
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")


def req_datetime(body, field):
    v = req_str(body, field)
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


def require_path_resource(collection, rid):
    """Tier 5: path parameter existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Tier 5: body-supplied foreign key existence (validated in declared order)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj


def get_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
