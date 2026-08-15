"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD validations 1-2).

Every request carries X-User-ID and X-User-Role. Roles: PDSO, DSO, Student.
PDSO/DSO identifiers are opaque operator ids; Student's X-User-ID is the id of
the acting Student resource (entity-backed).
"""

from flask import request

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_error,
)

ROLES = ("PDSO", "DSO", "Student")
ALL_ROLES = ROLES
STAFF_ROLES = ("PDSO", "DSO")


def get_caller():
    """Validate the auth headers (validation priority 1) and return
    (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        not isinstance(user_id, str)
        or not user_id
        or not isinstance(role, str)
        or role not in ROLES
    ):
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    return user_id, role


def require_roles(allowed_roles):
    """Endpoint-level role permission (validation priority 2)."""
    user_id, role = get_caller()
    if role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted on this endpoint",
        )
    return user_id, role
