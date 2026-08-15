"""Request-body validation helpers.

Domain-rule errors (state, gates, temporal, constraints) fire before schema
validation per PRD 2.10 — callers run `*_soft` probes during domain checks and
the strict `req_*` validators last (priority 8, ERR_VALIDATION 400).
"""
from datetime import datetime, date

from db import db
from errors import raise_error, ERR_NOT_FOUND, ERR_VALIDATION
from util import is_valid_date_str, is_valid_datetime_str


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Strict validators (priority 8 -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

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


def req_int(body, field, non_negative=False, positive=False):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"missing or invalid integer field: {field}")
    if non_negative and v < 0:
        raise_error(ERR_VALIDATION, f"field {field} must be >= 0")
    if positive and v <= 0:
        raise_error(ERR_VALIDATION, f"field {field} must be > 0")
    return v


def opt_int(body, field, default=None, non_negative=False, positive=False):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, non_negative=non_negative, positive=positive)


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_VALIDATION, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_VALIDATION, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_date(body, field):
    v = body.get(field)
    if not is_valid_date_str(v):
        raise_error(ERR_VALIDATION, f"missing or invalid ISO date field: {field}")
    return v.strip()


def opt_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_date(body, field)


def req_datetime(body, field):
    v = body.get(field)
    if not is_valid_datetime_str(v):
        raise_error(ERR_VALIDATION, f"missing or invalid ISO datetime field: {field}")
    return v.strip()


def req_str_list(body, field, non_empty=False):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(i, str) for i in v):
        raise_error(ERR_VALIDATION, f"field {field} must be an array of strings")
    if non_empty and len(v) == 0:
        raise_error(ERR_VALIDATION, f"field {field} must be a non-empty array")
    return list(v)


def opt_version(body, field):
    """Optional OCC field: when present it must be an integer (schema)."""
    if field not in body or body.get(field) is None:
        return None
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"field {field} must be an integer")
    return v


# ---------------------------------------------------------------------------
# Soft probes used during domain checks (no raising)
# ---------------------------------------------------------------------------

def soft_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def soft_str(v):
    return isinstance(v, str) and v.strip() != ""


def soft_date(v):
    return is_valid_date_str(v)


# ---------------------------------------------------------------------------
# Existence (priority 3 -> ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------

def require_path_resource(collection, rid):
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_ref(collection, rid, field):
    """Body-supplied foreign key existence. None passes (absent -> schema)."""
    if rid is None:
        return None
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{field} does not resolve: {rid}")
    return obj
