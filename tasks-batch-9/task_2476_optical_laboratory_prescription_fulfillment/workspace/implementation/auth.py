"""Role-based access control (PRD 2.1, validation priority 40)."""

from flask import request

from errors import ApiError

ROLES = (
    "StoreOptician",
    "Prescriber",
    "LabTechnician",
    "QualityInspector",
    "LabManager",
    "BenefitsAdministrator",
)

ANY = ROLES


def acting_role():
    # PRD 2.1: the acting role travels in X-User-Role and nowhere else.
    return request.headers.get("X-User-Role")


def acting_user_id():
    return request.headers.get("X-User-ID")


def require_roles(*allowed):
    """Both headers must be present, the role known, and permitted here."""
    user_id = acting_user_id()
    role = acting_role()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHORIZED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role
