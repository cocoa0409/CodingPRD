"""Auth header extraction and role checks (PRD 2.1; validation tiers 2-3)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {
    "HarnessEngineer",
    "ProcessEngineer",
    "QualityManager",
    "QualityInspector",
    "ProductionPlanner",
    "MaterialsClerk",
    "LineOperator",
    "ShippingClerk",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles) -> Caller:
    """Tier 2 (authentication) then tier 3 (authorization)."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must be present and the role "
                    "must be one of the declared roles")
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {role} is not authorized for this endpoint")
    return Caller(user_id, role)
