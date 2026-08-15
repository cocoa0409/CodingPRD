"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {"ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"}

MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-Role must name a declared role; X-User-ID required on mutating requests."""
    role = request.headers.get("X-User-Role", "").strip()
    user_id = request.headers.get("X-User-ID", "").strip()
    if not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED, "X-User-Role header missing or not a declared role")
    if request.method in MUTATING_METHODS and not user_id:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID header required on mutating requests")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
