"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_COORDINATOR = "DistrictSafetyCoordinator"
ROLE_OFFICER = "SchoolSafetyOfficer"
ROLE_PRINCIPAL = "Principal"
ROLE_RESPONDER = "FirstResponder"
ROLE_AUDITOR = "StateAuditor"

ALL_ROLES = [ROLE_COORDINATOR, ROLE_OFFICER, ROLE_PRINCIPAL, ROLE_RESPONDER, ROLE_AUDITOR]
_ROLE_SET = set(ALL_ROLES)


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-Role must be present and one of the declared roles."""
    role = request.headers.get("X-User-Role", "").strip()
    if not role or role not in _ROLE_SET:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-Role header missing or not a declared role")
    user_id = request.headers.get("X-User-ID")
    if user_id is not None:
        user_id = user_id.strip() or None
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: authentication then endpoint role authorization."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not authorized for this endpoint")
    return caller
