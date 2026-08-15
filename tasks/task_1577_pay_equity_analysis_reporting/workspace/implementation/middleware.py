"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ALL_ROLES = {
    "CompAnalyst",
    "LegalCounsel",
    "RemediationApprover",
    "PeopleOpsAdmin",
    "ComplianceReporter",
    "PlatformAdmin",
}

# Roles allowed on every GET endpoint ("All roles" in the endpoint table).
ALL_READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present; role in the declared set."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "" or role is None or str(role).strip() == "":
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            f"X-User-Role value is not a declared role: {role}",
        )
    return Caller(str(user_id).strip(), role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
