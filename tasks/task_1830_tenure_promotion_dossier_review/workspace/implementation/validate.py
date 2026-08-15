"""Request-body shape validation (priority 9, ERR_INVALID_REQUEST /
ERR_INVALID_INTERVAL) plus path/body reference resolution (priorities 3-4).

Per PRD §2.12, malformed-request failures sit at priority 9 — AFTER existence,
ownership, stage, state, and safety checks. Routes therefore read raw body
values leniently for early-priority checks and only call the strict req_*
readers once priorities 1-8 have passed.
"""
from db import db
from errors import raise_error, ERR_INVALID_REQUEST


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Lenient reads (never raise) — for early-priority checks
# ---------------------------------------------------------------------------

def raw(body, field):
    return body.get(field)


def raw_str(body, field):
    """The field's value if it is a non-empty string, else None."""
    v = body.get(field)
    if isinstance(v, str) and v.strip() != "":
        return v
    return None


def raw_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def raw_bool(body, field):
    v = body.get(field)
    return v if isinstance(v, bool) else None


# ---------------------------------------------------------------------------
# Strict readers (priority 9 — ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def opt_nullable_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
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


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def opt_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field)


def req_datetime_str(body, field):
    """Required ISO 8601 date/datetime string (stored verbatim)."""
    v = req_str(body, field)
    from util import is_valid_dt
    if not is_valid_dt(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime: {field}")
    return v


# ---------------------------------------------------------------------------
# Path / body reference resolution (priorities 3-4)
# ---------------------------------------------------------------------------

def require_path(collection, rid, error_spec):
    """Priority 3: path parameter existence with the entity-specific error id."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(error_spec, f"{collection} id not found: {rid}")
    return obj


def body_ref_exists(collection, value):
    """Priority 4 helper: existence of a body-carried FK. Only meaningful when
    the raw value is a non-empty string (other shapes fall to priority 9)."""
    if not isinstance(value, str) or value == "":
        return None
    return db[collection].get(value)
