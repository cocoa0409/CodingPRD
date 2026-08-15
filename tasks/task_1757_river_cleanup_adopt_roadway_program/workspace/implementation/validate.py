"""Request-body shape validation (validation family 5) and reference
resolution helpers (family 3), per PRD 2.11."""
from datetime import date, datetime

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_GROUP_NOT_FOUND,
    ERR_SEGMENT_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_WAIVER_NOT_FOUND,
    ERR_SUPPLY_NOT_FOUND,
    ERR_DEPOT_NOT_FOUND,
    ERR_HAZARD_NOT_FOUND,
    ERR_SIGN_NOT_FOUND,
)

NOT_FOUND_FOR = {
    "groups": ERR_GROUP_NOT_FOUND,
    "segments": ERR_SEGMENT_NOT_FOUND,
    "agreements": ERR_AGREEMENT_NOT_FOUND,
    "events": ERR_EVENT_NOT_FOUND,
    "waivers": ERR_WAIVER_NOT_FOUND,
    "supplies": ERR_SUPPLY_NOT_FOUND,
    "depots": ERR_DEPOT_NOT_FOUND,
    "hazards": ERR_HAZARD_NOT_FOUND,
    "signs": ERR_SIGN_NOT_FOUND,
}


def get_body():
    from flask import request
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


def opt_nullable_str(body, field, default=None):
    """A string field that may legitimately be set to null (PATCH semantics)."""
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


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


def req_number(body, field):
    """A JSON number (int or float; bool rejected)."""
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def opt_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field)


def parse_iso_date(v, field):
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")
    try:
        return date.fromisoformat(v.strip())
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO date: {field}")


def req_date(body, field):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {field}")
    return parse_iso_date(v, field)


def req_datetime_str(body, field):
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


def require_resource(collection, rid, spec=None):
    """Family 3: reference existence; each collection has its own 404 code."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(spec or NOT_FOUND_FOR[collection], f"{collection} id not found: {rid}")
    return obj


def maybe_resource(collection, rid, spec=None):
    """Resolve an optional reference; None passes through."""
    if rid is None:
        return None
    return require_resource(collection, rid, spec)


def ref_id(body, field):
    """A body reference field: absent -> None; must be a non-empty string otherwise."""
    if field not in body or body.get(field) is None:
        return None
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"invalid reference field: {field}")
    return v
