"""Auth middleware: identity headers and role authorization (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The five declared roles
are DepartmentChair, FacultyMember, DeanOffice, Registrar, SystemAdmin.
"""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {"DepartmentChair", "FacultyMember", "DeanOffice", "Registrar", "SystemAdmin"}

CHAIR = "DepartmentChair"
FACULTY = "FacultyMember"
DEAN = "DeanOffice"
REGISTRAR = "Registrar"
ADMIN = "SystemAdmin"

ALL_ROLES = [CHAIR, FACULTY, DEAN, REGISTRAR, ADMIN]


def current_context():
    """Priority 1: both headers present and role is a declared role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip() or role is None or not str(role).strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            f"X-User-Role {role!r} is not a declared role",
        )
    return user_id, role


def authenticate(allowed_roles):
    """Priority 1 (headers) then priority 2 (endpoint-level role gate).
    Returns (user_id, role)."""
    user_id, role = current_context()
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            f"role {role} is not permitted for this endpoint",
        )
    return user_id, role


def require_to_state_role(role, to_state, allowed_by_state):
    """Priority 2 per-to_state role gate on shared transition endpoints.

    allowed_by_state maps a to_state value to the set of roles permitted to
    request it. A to_state granted to no role is denied for everyone.
    """
    permitted = allowed_by_state.get(to_state, set())
    if role not in permitted:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            f"role {role} is not permitted for to_state {to_state}",
        )
