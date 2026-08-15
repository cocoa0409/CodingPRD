from flask import request

from errors import ApiError

ROLES = {"PlantManager", "LineOperator", "QualityTechnician", "RoutePlanner", "CoManufacturer"}

ALL_ROLES = ["PlantManager", "LineOperator", "QualityTechnician", "RoutePlanner", "CoManufacturer"]


def require(allowed=None):
    """Validation tiers 1-2: authentication then endpoint role authorization.

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid == "" or role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and role must be declared")
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "role not authorized for this endpoint")
    return uid, role
