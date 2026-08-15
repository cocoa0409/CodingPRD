"""Auth header extraction and role authorization (PRD 2.1, validation stages 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

# The five declared roles, spelled exactly as in PRD 2.1.
DECLARED_ROLES = {"PolicyAdmin", "AuthCoordinator", "MedicalDirector", "FinanceSpecialist", "Scheduler"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def authorized(allowed_roles) -> Caller:
    """Stage 1: X-User-ID and X-User-Role present, role declared (401).
    Stage 2: role listed for the endpoint (403)."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and the role must be declared")
    if role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    f"role {role} is not authorized for this endpoint")
    return Caller(user_id, role)
