"""Identity headers and role authorisation (PRD section 2.1)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "RegulatoryAdmin",
    "CustomerRep",
    "CycleOperator",
    "DosimetryAnalyst",
    "QualityReleaseOfficer",
)


def authenticate(*allowed_roles):
    """Validation priority 10 then 20."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role
    return user_id, role


def customer_scope(customer_id):
    """Validation priority 40 - the CustomerRep ownership rule."""
    if g.role == "CustomerRep" and g.user_id != customer_id:
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
