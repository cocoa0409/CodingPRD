"""Auth header extraction, RBAC, field validation, pagination parsing."""
from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "EnrollmentCoordinator",
    "Physician",
    "MonitoringTechnician",
    "BillingSpecialist",
    "InventoryManager",
    "DeviceGateway",
}
READ_ROLES = ROLES - {"DeviceGateway"}


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-Role or X-User-ID")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role not permitted for this endpoint")


def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req(data, name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field must be a non-empty string: {name}")
    return v


def req_enum(data, name, allowed):
    v = req(data, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Invalid value for {name}")
    return v


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    if data[name] not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Invalid value for {name}")
    return data[name]


def req_int(data, name, lo=None, hi=None):
    v = req(data, name)
    if not is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field must be an integer: {name}")
    if lo is not None and v < lo:
        raise ApiError("ERR_VALIDATION", 400, f"{name} out of range")
    if hi is not None and v > hi:
        raise ApiError("ERR_VALIDATION", 400, f"{name} out of range")
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field must be a boolean: {name}")
    return data[name]


def pagination():
    limit, offset = 10, 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "Invalid offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def sorted_by_creation(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))
