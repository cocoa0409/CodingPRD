"""Request-body shape validation (PRD 2.9 category 13) and reference resolution.

Pure shape failures (missing required field, bad enum/type, unknown payload
field, non-positive amount, inverted date range) are detected before any
stateful evaluation, per the scaffold validation-table note and the pinned
corner cases (missing-field + bogus-FK dual failures surface as shape errors).
"""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import parse_dt


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def reject_unknown_fields(body: dict, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        raise_error(ERR_INVALID_REQUEST, f"unknown payload field(s): {', '.join(sorted(extra))}")


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


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if v is None or not _is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be > 0")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return v


def opt_int(body, field, default=None, positive=False, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, positive=positive, non_negative=non_negative)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_number(body, field):
    v = body.get(field)
    if v is None or not _is_number(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def opt_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field)


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_datetime(body, field):
    """Required ISO-8601 datetime string; returns the raw string."""
    v = req_str(body, field)
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def version_field(body, field):
    """OCC version guard field: integer (a numeric string is tolerated)."""
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {field}")
    if _is_int(v):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    raise_error(ERR_INVALID_REQUEST, f"invalid version field: {field}")


def get_pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
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


def require_path_resource(collection, rid):
    """Priority 3: path identifiers resolve, left to right."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_body_ref(collection, rid, field):
    """Priority 3: body foreign-key references resolve (after path ids)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"body reference {field} does not resolve: {rid}")
    return obj
