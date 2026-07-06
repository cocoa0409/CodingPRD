"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.10, scaffold §1.7).

Auth headers: X-User-ID (acting user), X-User-Role (role capacity).
Roles: Physician, Practitioner, BillingSpecialist, ComplianceOfficer.
"""
from flask import request

from errors import ApiError

ROLES = {"Physician", "Practitioner", "BillingSpecialist", "ComplianceOfficer"}


def get_auth():
    """Validate auth headers. Returns (user_id, role). Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is in `allowed`. Raises ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted for this operation." % role)
