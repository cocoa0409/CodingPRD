"""Authentication, role permission and ownership-scope checks (PRD sections 2.1, 2.8)."""

from flask import request

from errors import ApiError

ROLES = (
    "BrokerAdmin",
    "BrokerAccountManager",
    "BrokerAuditManager",
    "RetailerBuyer",
    "PrincipalPortalUser",
)

ALL_ROLES = list(ROLES)
BROKER_ROLES = ["BrokerAdmin", "BrokerAccountManager", "BrokerAuditManager"]


def actor():
    """Band 1 — authentication."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(*allowed):
    """Bands 1 and 2 — authentication then role permission."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return user_id, role


def check_retailer_scope(role, user_id, retailer_id):
    """Band 5 — a RetailerBuyer may only write inside its own chain."""
    if role == "RetailerBuyer" and retailer_id != user_id:
        raise ApiError("ERR_RETAILER_SCOPE_FORBIDDEN")


def check_principal_scope(role, user_id, principal_id):
    """Band 5 — a PrincipalPortalUser may only read its own principal's resources."""
    if role == "PrincipalPortalUser" and principal_id != user_id:
        raise ApiError("ERR_PRINCIPAL_SCOPE_FORBIDDEN")
