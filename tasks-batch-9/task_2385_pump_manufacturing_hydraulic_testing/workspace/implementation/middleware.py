"""Authentication and role checking (PRD section 2.1)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "ApplicationEngineer",
    "HydraulicApprover",
    "FoundryPartner",
    "QualityInspector",
    "TestEngineer",
    "ProductionPlanner",
    "WarrantyAdjudicator",
)

ALL_ROLES = ROLES


def authenticate():
    """Rung 1 of the rejection ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id)
    g.role = role
    return g.user_id, g.role


def authorize(*allowed):
    """Rungs 1 then 2 of the rejection ladder."""
    user_id, role = authenticate()
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role
