"""Auth header extraction and RBAC (PRD §2.1, §2.10).

Every request carries X-User-ID (acting user) and X-User-Role (operational
capacity). Recognized roles: SchoolAdmin, Instructor, Student.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

KNOWN_ROLES = {"SchoolAdmin", "Instructor", "Student"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/unknown.

    Auth is checked first (priority 1). A missing or unknown X-User-Role yields
    ERR_UNAUTHENTICATED (PRD §2.1).
    """
    role = request.headers.get(ROLE_HEADER)
    if role is None or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role")
    user_id = request.headers.get(ID_HEADER)
    return user_id, role


def require_role(role, allowed):
    """Authorization check (priority 2). Recognized but unpermitted -> ERR_FORBIDDEN."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, f"role {role} not permitted for this operation")
