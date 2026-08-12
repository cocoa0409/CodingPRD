"""Auth context (PRD 2.1), role authorization, and body field validators (2.8)."""
from flask import request

from errors import ApiError

ROLES = {
    "PurchasingAgent",
    "BrandApprover",
    "Vendor",
    "WarehouseReceiver",
    "InstallationManager",
    "OwnerRep",
}


def auth():
    """Stage 1: X-User-ID and X-User-Role present; role one of the six."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and role must be "
            "one of the six declared roles",
        )
    return uid, role


def require_role(role, allowed):
    """Stage 2: role is listed for this endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", f"Role {role} is not permitted for this endpoint"
        )


def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(d, key):
    v = d.get(key)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid field: {key}")
    return v


def req_int(d, key, minimum=None):
    v = d.get(key)
    if not _is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", f"Missing or invalid integer field: {key}")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be >= {minimum}")
    return v


def opt_int(d, key, default, minimum=None):
    if key not in d or d[key] is None:
        return default
    return req_int(d, key, minimum)


def req_enum(d, key, values):
    v = d.get(key)
    if not isinstance(v, str) or v not in values:
        raise ApiError(
            "ERR_INVALID_REQUEST", f"Field {key} must be one of {sorted(values)}"
        )
    return v


def opt_bool(d, key, default):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {key} must be a boolean")
    return v
