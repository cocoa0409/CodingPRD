from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_SCOPE_MISMATCH,
)

ALL_ROLES = [
    "ProgramAdmin",
    "HostCoordinator",
    "RespondingCoordinator",
    "CrewSupervisor",
    "HostSafetyOfficer",
    "HostFinance",
    "RespondingFinance",
]


class CallerContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_admin(self):
        return self.role == "ProgramAdmin"


def get_caller():
    """Priority 1: header presence/validity."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID header missing or malformed",
            400,
        )
    if not role or role not in ALL_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role header missing or malformed",
            400,
        )
    return CallerContext(uid, role)


def require_role(caller, allowed_roles):
    """Priority 2: role admission for the endpoint."""
    if caller.role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            f"Role {caller.role} is not permitted for this endpoint",
            403,
        )


def require_scope(caller, expected_id):
    """Priority 3: ownership scope for entity-backed callers."""
    if caller.is_admin():
        return
    if caller.user_id != expected_id:
        raise ApiError(
            ERR_SCOPE_MISMATCH,
            "Caller identity does not match the resource's owning scope",
            403,
        )
