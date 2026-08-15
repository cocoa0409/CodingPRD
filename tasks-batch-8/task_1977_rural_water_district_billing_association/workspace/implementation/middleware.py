"""Auth context, role checks, request-body validation, scoped lookups."""
import functools

from flask import request

import db
from errors import ApiError

ROLES = ["SystemAdmin", "BillingClerk", "Treasurer", "BoardDirector", "FieldOperator"]
ALL_ROLES = list(ROLES)


def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and the role must be one of the declared roles",
        )
    return user_id, role


def require_roles(allowed):
    """Decorator: auth context first (400), then role permission (403)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role %s is not permitted for this endpoint" % role,
                )
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return deco


def body():
    """Return the JSON request body as a dict, or {} when absent."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be a string" % field)
    return v


def req_int(b, field, minimum=None, strict_minimum=None):
    v = b.get(field)
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be >= %d" % (field, minimum))
    if strict_minimum is not None and v <= strict_minimum - 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be >= %d" % (field, strict_minimum))
    return v


def opt_int(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % field)
    return v


def opt_enum(b, field, values, default=None):
    v = b.get(field)
    if v is None:
        return default
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be one of %s" % (field, ", ".join(values)))
    return v


def req_enum(b, field, values):
    v = b.get(field)
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be one of %s" % (field, ", ".join(values)))
    return v


def req_dt(b, field):
    v = b.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be an ISO8601 string" % field)
    try:
        return v, db.parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a valid ISO8601 datetime" % field)


def opt_dict(b, field):
    v = b.get(field)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an object" % field)
    return v


# ---------------------------------------------------------------- lookups

def get_district(district_id):
    d = db.districts.get(district_id)
    if d is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND", 404, "District %s does not exist" % district_id)
    return d


def get_scoped(store, entity_id, district_id, error_id, label):
    e = store.get(entity_id)
    if e is None or e.get("district_id") != district_id:
        raise ApiError(error_id, 404, "%s %s does not exist in this district" % (label, entity_id))
    return e


def get_bare(store, entity_id, error_id, label):
    e = store.get(entity_id)
    if e is None:
        raise ApiError(error_id, 404, "%s %s does not exist" % (label, entity_id))
    return e
