"""Request-shape validation (priority 4) and existence checks (priority 5)."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_INVALID_PAGINATION_PARAMETERS,
    ERR_NOT_FOUND,
)
from util import parse_dt


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_VALIDATION, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"field {field} below minimum {minimum}")
    return v


def req_number(body, field, gt=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_VALIDATION, f"missing or invalid numeric field: {field}")
    if gt is not None and not v > gt:
        raise_error(ERR_VALIDATION, f"field {field} must be > {gt}")
    return v


def req_enum(body, field, options):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in options:
        raise_error(
            ERR_VALIDATION,
            f"field {field} must be one of {sorted(options)}",
        )
    return v


def opt_enum(body, field, options, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in options:
        raise_error(
            ERR_VALIDATION,
            f"field {field} must be one of {sorted(options)}",
        )
    return v


def req_dt(body, field):
    """Required ISO8601 datetime. Returns (raw_string, parsed_datetime)."""
    raw = body.get(field)
    if raw is None or not isinstance(raw, str):
        raise_error(ERR_VALIDATION, f"missing or invalid datetime field: {field}")
    try:
        parsed = parse_dt(raw)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, f"field {field} is not a valid ISO8601 datetime")
    return raw, parsed


def get_pagination():
    """List pagination (priority 4): 1 <= limit <= 100, offset >= 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_error(ERR_INVALID_PAGINATION_PARAMETERS, "offset must be >= 0")
    return limit, offset


def require_path_resource(collection, rid, label=None):
    """Priority 5: path ids resolve left to right."""
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{label or collection} not found: {rid}")
    return rec


def require_body_ref(collection, rid, field):
    """Priority 5: body foreign keys validated in declared input order."""
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"referenced {field} not found: {rid}")
    return rec
