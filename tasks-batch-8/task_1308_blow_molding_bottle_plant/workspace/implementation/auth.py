"""Authentication (X-User-ID / X-User-Role) and role authorization."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlantAdmin",
    "ProcessEngineer",
    "QualityTechnician",
    "ProductionScheduler",
    "LogisticsCoordinator",
    "CustomerQualityRep",
}


def authenticate():
    """Priority-1 check: both headers present, role declared, id non-empty."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED,
                  "X-User-Role header missing or not a declared role")
    if user_id is None or user_id == "":
        raise_err(ERR_UNAUTHENTICATED,
                  "X-User-ID header missing or empty")
    return user_id, role


def require_role(role, allowed):
    """Priority-2 check: acting role listed for the endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % role)
