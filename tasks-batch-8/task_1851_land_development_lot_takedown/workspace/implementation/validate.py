"""Request-body shape validation (priority 4) and existence helpers (priority 3).

Validation order (PRD 2.8): auth (1) -> role/ownership (2) -> existence (3) ->
shape (4) -> OCC (5) -> state (6) -> SoD (7) -> temporal (8) ->
uniqueness/overlap/capacity (9) -> referential (10) -> fiscal (11).
"""
from datetime import datetime

from flask import request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_PARCEL_NOT_FOUND,
    ERR_PHASE_NOT_FOUND,
    ERR_BOND_NOT_FOUND,
    ERR_BUILDER_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_CLOSING_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_DRAW_NOT_FOUND,
    ERR_HOA_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_CONNECTION_NOT_FOUND,
)
from util import fmt_dt, parse_dt

NOT_FOUND_FOR_COLLECTION = {
    "parcels": ERR_PARCEL_NOT_FOUND,
    "phases": ERR_PHASE_NOT_FOUND,
    "bonds": ERR_BOND_NOT_FOUND,
    "builders": ERR_BUILDER_NOT_FOUND,
    "agreements": ERR_AGREEMENT_NOT_FOUND,
    "lots": ERR_LOT_NOT_FOUND,
    "closings": ERR_CLOSING_NOT_FOUND,
    "loans": ERR_LOAN_NOT_FOUND,
    "draws": ERR_DRAW_NOT_FOUND,
    "hoas": ERR_HOA_NOT_FOUND,
    "providers": ERR_PROVIDER_NOT_FOUND,
    "connections": ERR_CONNECTION_NOT_FOUND,
}


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


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


def req_int(body, field, minimum=None, maximum=None, non_negative=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if non_negative and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= 0")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None, non_negative=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum, non_negative=non_negative)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def _validate_datetime(v, field):
    try:
        parse_dt(v)
    except (ValueError, TypeError, AttributeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")


def req_datetime(body, field):
    """Required datetime; returns the value normalized to UTC second precision."""
    v = req_str(body, field)
    _validate_datetime(v, field)
    return fmt_dt(parse_dt(v))


def opt_datetime(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_datetime(body, field)


def get_pagination():
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


def require_path(collection, rid):
    """Priority 3: path parameter existence (single id per flat URL)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(NOT_FOUND_FOR_COLLECTION[collection], f"{collection} id not found: {rid}")
    return obj


def fk_lookup(collection, value):
    """Look up a body-supplied FK; only string values can resolve."""
    if not isinstance(value, str):
        return None
    return db[collection].get(value)


def check_body_fk_exists(collection, body, field):
    """Priority 3: body FK existence. A present string that does not resolve
    fails with the resource's 404; a missing/non-string field is deferred to
    the priority-4 shape checks. Returns the record (or None)."""
    value = body.get(field)
    rec = fk_lookup(collection, value)
    if rec is None and isinstance(value, str):
        raise_error(NOT_FOUND_FOR_COLLECTION[collection], f"{field} does not resolve: {value}")
    return rec
