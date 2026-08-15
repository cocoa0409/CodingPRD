"""Auth header extraction and role checks (PRD 2.1, validation rungs 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
)

# The three declared role names, spelled exactly (PRD 2.1).
ALL_ROLES = ("AidDirector", "AidOfficer", "Student")


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Rung 1: both headers present and the role is a declared role name."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are both required")
    if role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    f"X-User-Role '{role}' is not a declared role")
    return Caller(user_id.strip(), role.strip())


def check_role_allowed(caller: Caller, allowed_roles):
    """Rung 2: the caller's role must be listed for the endpoint."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller


def check_student_owns(caller: Caller, owner_student_id: str):
    """Rung 8: a Student-role caller may act only on their own resources.

    Only applied to Student-role callers; AidDirector/AidOfficer identities are
    opaque and never compared to entity ids (PRD 2.1).
    """
    if caller.role == "Student" and caller.user_id != owner_student_id:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "student caller does not own this resource")
