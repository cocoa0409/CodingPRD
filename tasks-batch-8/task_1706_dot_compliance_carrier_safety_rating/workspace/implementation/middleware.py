"""Auth header extraction and role checks (PRD 2.1, validation pipeline stages 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT,
    ERR_FORBIDDEN_ROLE,
)

ALL_ROLES = {
    "SafetyAdmin",
    "SafetyDirector",
    "SafetyManager",
    "ComplianceAnalyst",
    "MedicalReviewOfficer",
    "InsuranceAnalyst",
}

READ_ROLES = sorted(ALL_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Stage 1: X-User-ID / X-User-Role present, non-empty, and role declared."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT,
                    "X-User-ID and X-User-Role headers must both be present and non-empty")
    if role not in ALL_ROLES:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT,
                    f"unknown role: {role}")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Stage 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
