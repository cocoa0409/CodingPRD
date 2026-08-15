"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {
    "PlanAdministrator",
    "ClaimsExaminer",
    "StopLossAnalyst",
    "CarrierReviewer",
    "PlanAccountant",
    "CarrierAuditor",
}


class Caller:
    """X-User-ID is opaque for every role (PRD §2.1) — recorded, never scoped."""

    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present, non-empty, role recognized."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers must both be present and the role "
            "must be one of the six recognized roles",
        )
    return Caller(user_id, role)


def require_role(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN,
            f"role {caller.role} is not permitted to invoke this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_role(caller, allowed_roles)
    return caller
