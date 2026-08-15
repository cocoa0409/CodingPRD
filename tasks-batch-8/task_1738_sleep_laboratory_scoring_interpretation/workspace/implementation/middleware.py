"""Auth header extraction and role checks (PRD 2.1; validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ALL_ROLES = [
    "Scheduler",
    "SleepTechnologist",
    "Scorer",
    "InterpretingPhysician",
    "DmeCoordinator",
    "LabDirector",
]
_ROLE_SET = set(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present and role recognized."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in _ROLE_SET:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: authentication, then role authorization for the endpoint."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not permitted for this endpoint")
    return caller
