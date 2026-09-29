"""Authentication and role authorisation (PRD section 2.1, ladder rungs 1-2)."""

from flask import request

from errors import ApiError

ROLES = (
    "PlantAdmin",
    "DesignEngineer",
    "StructuralReviewer",
    "ProductionOperator",
    "QAEngineer",
    "FieldEngineer",
    "ServiceManager",
)

ALL_ROLES = ROLES


def authenticate():
    """Rung 1: both headers present and the role is one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require(*allowed_roles):
    """Rungs 1 then 2. Returns (user_id, role)."""
    user_id, role = authenticate()
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role
