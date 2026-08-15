"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ALL_ROLES = {"ProgramAdmin", "KitchenManager", "FoodSafetyOfficer", "Volunteer", "Guest"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-Role and X-User-ID present; role value recognized."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and role must be recognized")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")
