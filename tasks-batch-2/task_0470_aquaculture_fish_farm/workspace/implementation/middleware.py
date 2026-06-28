"""Auth header extraction and RBAC. Header names and role values come verbatim
from PRD §2.1."""
from flask import request

import errors

KNOWN_ROLES = {"FarmManager", "FarmTechnician", "Veterinarian", "HarvestOperator", "SalesAgent"}


def get_role():
    """PRD §2.1: every request carries X-User-ID (opaque) and X-User-Role.
    Missing either header, or an X-User-Role that is not a known role ->
    ERR_UNAUTHENTICATED (401). Applies to every endpoint including the clock."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "":
        raise errors.unauthenticated()
    if role is None or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return role


def require_roles(allowed_roles):
    """Validate auth (401) then RBAC (403) in PRD §2.12 precedence order."""
    role = get_role()
    if role not in allowed_roles:
        raise errors.forbidden_role()
    return role


ALL_ROLES = KNOWN_ROLES
