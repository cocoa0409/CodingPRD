"""Request-body field helpers (tier-9 constraint checks) and FK/path resolvers (tier 4)."""
from flask import request

import db
from errors import ApiError


def get_body():
    """Parse the JSON request body; unknown/extra fields are ignored by callers."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def _bad(field, msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s': %s" % (field, msg))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        _bad(field, "is required and must be a non-empty string")
    return v


def opt_string(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        _bad(field, "is required and must be an integer")
    return v


def opt_int(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not is_int(v):
        _bad(field, "must be an integer")
    return v


def req_number(body, field):
    v = body.get(field)
    if not is_number(v):
        _bad(field, "is required and must be a number")
    return v


def opt_number(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not is_number(v):
        _bad(field, "must be a number")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return v


def opt_enum(body, field, allowed, default=None):
    v = body.get(field, default)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        _bad(field, "is required and must be an array")
    return v


def req_datetime(body, field):
    """Parse a required ISO 8601 datetime field to an aware UTC datetime."""
    v = body.get(field)
    dt = db.parse_iso(v)
    if dt is None:
        _bad(field, "is required and must be an ISO 8601 datetime")
    return dt


def present(body, field):
    """True when the field is present and non-null in the body."""
    return field in body and body[field] is not None


def resolve_fk(table, fk_id, error_id):
    """Tier-4 existence for a request-body foreign key."""
    ent = table.get(fk_id) if isinstance(fk_id, str) else None
    if ent is None:
        raise ApiError(error_id, 404, "Referenced resource does not exist: %s" % fk_id)
    return ent


def resolve_path(table, entity_id, error_id):
    """Tier-4 existence for a path identifier."""
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError(error_id, 404, "Resource not found: %s" % entity_id)
    return ent
