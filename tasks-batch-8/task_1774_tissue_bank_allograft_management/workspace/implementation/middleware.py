"""Auth header extraction and role authorization (PRD §2.1, validation rungs 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ALL_ROLES = {
    "TissueBankCoordinator",
    "QualityManager",
    "ComplianceOfficer",
    "ImplantingSurgeon",
    "SupplyChainAdmin",
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def require_roles(allowed_roles) -> Caller:
    """Rung 1 (header presence + role vocabulary, 400) then rung 2 (role listed
    for the endpoint, 403)."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be one of the five declared roles",
        )
    caller = Caller(user_id, role)
    if caller.role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {caller.role} is not authorized for this endpoint",
        )
    return caller
