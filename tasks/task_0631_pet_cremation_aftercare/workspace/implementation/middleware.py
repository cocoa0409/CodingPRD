"""Auth header extraction and role validation (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role. X-User-Role must name one of
the four recognized roles. Missing header or unknown role -> ERR_UNAUTHENTICATED.
"""

from flask import request

import errors

ROLES = {"CrematoryAdmin", "CrematoryOperator", "ClinicStaff", "PetOwner"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers; return a Principal or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Enforce that the principal's role is in allowed_roles, else ERR_FORBIDDEN."""
    if principal.role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
