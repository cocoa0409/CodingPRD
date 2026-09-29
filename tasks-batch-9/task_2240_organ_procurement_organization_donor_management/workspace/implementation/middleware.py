"""Authentication and RBAC (PRD 2.1, rejection precedence steps 1-3)."""

from flask import request

from constants import ROLES
from errors import ApiError


def authenticate(*allowed_roles):
    """Precedence 1 (ERR_UNAUTHENTICATED) then 2 (ERR_FORBIDDEN_ROLE)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def enforce_hospital_scope(user_id, role, hospital_id):
    """Precedence 3 (ERR_HOSPITAL_SCOPE_VIOLATION).

    A HospitalReferralClerk's X-User-ID is the id of its own HospitalPartner.
    Evaluated before path/foreign-key existence, per PRD 2.10.
    """
    if role != "HospitalReferralClerk":
        return
    if hospital_id != user_id:
        raise ApiError("ERR_HOSPITAL_SCOPE_VIOLATION")
