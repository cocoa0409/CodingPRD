"""Authentication and role-based access control (PRD section 2.1)."""

from flask import request

from errors import ApiError

ROLES = {
    "DistributionAdmin",
    "SalesRep",
    "PracticeManager",
    "ServiceDispatcher",
    "FieldTechnician",
    "ManufacturerAgent",
}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or unknown X-User-Role / X-User-ID headers",
        )
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role is not permitted on this endpoint")


def auth_and_roles(allowed):
    uid, role = authenticate()
    require_roles(role, allowed)
    return uid, role


def pm_owns_or_403(role, uid, practice_id):
    """Entity-backed ownership: a PracticeManager may only touch resources whose
    practice_id equals their X-User-ID."""
    if role == "PracticeManager" and practice_id != uid:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "PracticeManager may only touch their own practice's resources",
        )
