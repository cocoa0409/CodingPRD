"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2).

Header scheme: X-User-ID + X-User-Role. Roles:
  LanguageAccessCoordinator, ComplianceOfficer  -> opaque operator ids
  DepartmentLiaison                             -> X-User-ID is a Department id
  Interpreter, QualityReviewer                  -> X-User-ID is an Interpreter id
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ALL_ROLES = {
    "LanguageAccessCoordinator",
    "DepartmentLiaison",
    "Interpreter",
    "QualityReviewer",
    "ComplianceOfficer",
}

ALL_READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: both headers present and the role is a declared role."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and the role must be a declared role",
        )
    return Caller(user_id, role)


def check_role(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            f"role {caller.role} is not permitted for this operation",
        )


def check_liaison_owns_department(caller: Caller, department_id):
    """Priority 2 ownership scope: a liaison's X-User-ID must equal the
    department_id being acted on. No-op for other roles and when the payload
    does not carry a department_id (shape validation reports that later)."""
    if caller.role == "DepartmentLiaison" and department_id is not None:
        if caller.user_id != department_id:
            raise_error(
                ERR_FORBIDDEN_ROLE,
                "DepartmentLiaison may act only on its own department",
            )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role(caller, allowed_roles)
    return caller
