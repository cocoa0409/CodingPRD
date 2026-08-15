"""Request-body schema validation (priority 4), path/body FK existence (priority 3),
query pagination parsing."""
from datetime import datetime

from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def reject_unknown_fields(body: dict, allowed):
    for key in body.keys():
        if key not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"unknown field: {key}")


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, non_negative=False, positive=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if positive and v <= 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 1")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def _check_iso_datetime(v, field):
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")


def req_datetime(body, field):
    v = req_str(body, field)
    _check_iso_datetime(v, field)
    return v


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def require_path(collection, rid, error_spec):
    """Priority 3: path identifier existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(error_spec, f"{collection[:-1]} not found: {rid}")
    return obj


def require_body_fk(collection, rid, error_spec, field):
    """Priority 3: body-carried foreign key existence."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(error_spec, f"{field} does not resolve: {rid}")
    return obj


def parse_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0).
    Out-of-range values are clamped."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
