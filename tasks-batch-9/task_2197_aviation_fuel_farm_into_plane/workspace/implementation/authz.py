"""Auth, RBAC and payload validation helpers."""
from flask import request

from core import ApiError, D, parse_dt

ROLES = {
    "ConsortiumAdmin", "FarmOperator", "QualityInspector", "IntoPlaneAgent",
    "AirlineRep", "EnvironmentalOfficer", "BillingClerk",
}

ALL_ROLES = sorted(ROLES)


def auth(*allowed):
    """Validate headers and endpoint role membership; return (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if allowed and role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation" % role)
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_PAYLOAD", "Request body must be a JSON object")
    return data


# ------------------------------------------------------------------ typing
def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(data, field, allow_empty=False):
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s is required and must be a string" % field)
    if not allow_empty and v == "":
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must not be empty" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be a string" % field)
    return v


def req_num(data, field):
    v = data.get(field)
    if not _is_num(v):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s is required and must be a number" % field)
    return D(v)


def opt_num(data, field, default=None):
    if field not in data or data.get(field) is None:
        return D(default) if default is not None else None
    v = data.get(field)
    if not _is_num(v):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be a number" % field)
    return D(v)


def req_int(data, field):
    v = data.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s is required and must be an integer" % field)
    return v


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be a boolean" % field)
    return v


def req_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s is required and must be an ISO 8601 string" % field)
    d = parse_dt(v)
    if d is None:
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be a valid ISO 8601 instant" % field)
    return d


def opt_dt(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be an ISO 8601 string" % field)
    d = parse_dt(v)
    if d is None:
        raise ApiError("ERR_INVALID_PAYLOAD", "%s must be a valid ISO 8601 instant" % field)
    return d


def req_id(data, field):
    return req_str(data, field)


def opt_id(data, field):
    return opt_str(data, field)


# ------------------------------------------------------------------ constraints
def rng(value, field, minimum=None, maximum=None, exclusive_min=False):
    if value is None:
        return value
    v = D(value)
    if minimum is not None:
        if exclusive_min:
            if v <= D(minimum):
                raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s must be greater than %s" % (field, minimum))
        elif v < D(minimum):
            raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s must be at least %s" % (field, minimum))
    if maximum is not None and v > D(maximum):
        raise ApiError("ERR_FIELD_OUT_OF_RANGE", "%s must be at most %s" % (field, maximum))
    return value


def enum(value, field, allowed):
    if value not in allowed:
        raise ApiError("ERR_FIELD_OUT_OF_RANGE",
                       "%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return value


def out_of_range(msg):
    raise ApiError("ERR_FIELD_OUT_OF_RANGE", msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_RESOURCE_NOT_FOUND", msg)


def ref_not_found(msg="Referenced entity not found"):
    raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", msg)


def resolve(coll, rid, msg=None):
    """Path-parameter resolution -> ERR_RESOURCE_NOT_FOUND."""
    row = coll.get(rid)
    if row is None:
        not_found(msg or "Resource %s not found" % rid)
    return row


def resolve_ref(coll, rid, msg=None):
    """Body FK resolution -> ERR_REFERENCED_ENTITY_NOT_FOUND."""
    row = coll.get(rid)
    if row is None:
        ref_not_found(msg or "Referenced entity %s not found" % rid)
    return row
