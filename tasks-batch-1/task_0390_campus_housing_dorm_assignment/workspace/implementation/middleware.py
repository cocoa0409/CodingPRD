"""Auth header extraction and role checking (PRD §2.1)."""

from flask import request

import errors

VALID_ROLES = {"HousingOfficer", "Student", "ResidentAdvisor"}
# Entity-backed roles whose X-User-ID is a Student.id.
ENTITY_BACKED_ROLES = {"Student", "ResidentAdvisor"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers. Raises ERR_UNAUTHENTICATED on failure.

    - X-User-Role must be present and one of the three known roles.
    - For entity-backed roles (Student, ResidentAdvisor), X-User-ID required.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role missing or not a known role.")

    if role in ENTITY_BACKED_ROLES and not user_id:
        raise errors.unauthenticated("X-User-ID required for entity-backed role.")

    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """RBAC check: caller's role must be among allowed_roles."""
    if principal.role not in allowed_roles:
        raise errors.forbidden("Role not permitted for this operation.")
