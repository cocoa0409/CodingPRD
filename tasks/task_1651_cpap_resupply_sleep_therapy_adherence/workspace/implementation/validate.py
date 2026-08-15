"""Request-body shape validation (lowest priority) and existence checks.

Evaluation order (PRD 2.7): auth -> role -> path existence (ERR_NOT_FOUND) ->
body FK existence (ERR_FK_NOT_FOUND) -> state/business rules -> malformed body
(ERR_INVALID_REQUEST) only when nothing earlier failed. Field-level validators
are therefore invoked lazily at the point the value is first needed.
"""
from datetime import date, datetime

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FK_NOT_FOUND


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Existence
# ---------------------------------------------------------------------------

def require_path_resource(collection, rid):
    """Path-parameter existence -> ERR_NOT_FOUND."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} resource not found: {rid}")
    return obj


def require_fk(collection, rid, field):
    """Body-referenced FK existence -> ERR_FK_NOT_FOUND (any unresolved value)."""
    obj = db[collection].get(rid)
    if obj is None:
        raise_error(ERR_FK_NOT_FOUND, f"body reference {field} does not resolve: {rid}")
    return obj


def fk_if_present(collection, rid):
    """FK lookup used for ordering: returns the record or None (caller decides)."""
    if rid is None:
        return None
    return db[collection].get(rid)


# ---------------------------------------------------------------------------
# Field validators (all raise ERR_INVALID_REQUEST, 400)
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid string field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type (expected string): {field}")
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


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def valid_iso_date(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        date.fromisoformat(v.strip())
        return True
    except (ValueError, TypeError):
        return False


def req_date(body, field):
    v = body.get(field)
    if not valid_iso_date(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid ISO date field: {field}")
    return v.strip()


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid ISO datetime field: {field}")
    s = v.strip()
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO datetime field: {field}")
    return s
