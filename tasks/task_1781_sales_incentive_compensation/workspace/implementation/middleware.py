"""Auth header extraction, role checks, and Rep ownership scoping (PRD 2.1)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_NOT_FOUND,
)

DECLARED_ROLES = {"CompAdmin", "CompAnalyst", "CompManager", "Rep"}
ALL_ROLES = DECLARED_ROLES


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence and role validity."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present with a declared role",
        )
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def check_rep_ownership(caller: Caller, rep_id: str):
    """Priority 3 ownership hiding: Rep callers only see own-linked resources.

    If the resource's rep linkage does not match the caller's X-User-ID,
    behave as if the resource does not exist.
    """
    if caller.role == "Rep" and caller.user_id != rep_id:
        raise_error(ERR_NOT_FOUND, "resource not found")


def authorized(allowed_roles) -> Caller:
    """Run auth priorities 1-2 for a request."""
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
