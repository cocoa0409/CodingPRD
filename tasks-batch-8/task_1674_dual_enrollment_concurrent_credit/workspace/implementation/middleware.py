"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-3).

Headers: X-User-ID (acting user) and X-User-Role (declared role name).
`Any` in the endpoint table is a marker meaning every declared role may call;
it is not itself a presentable role.
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

DECLARED_ROLES = {
    "DualCreditAdmin",
    "HsCoordinator",
    "Instructor",
    "CredentialReviewer",
    "CollegeRegistrar",
    "Bursar",
}

# Read endpoints marked "Any": every declared role may call.
ANY_ROLE = sorted(DECLARED_ROLES)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence and declared-role validity."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and X-User-Role "
            "must be a declared role",
        )
    return Caller(user_id, role)


def authorized(allowed_roles) -> Caller:
    """Priorities 1-2: header presence, then role membership for the endpoint."""
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise_error(
            ERR_UNAUTHORIZED_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )
    return caller
