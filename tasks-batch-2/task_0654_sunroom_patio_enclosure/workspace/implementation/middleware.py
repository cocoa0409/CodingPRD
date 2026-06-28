"""Auth header extraction and role checking (PRD §2.1, §2.7)."""
from flask import request, g

import errors

# The six recognized roles (PRD §2.1).
KNOWN_ROLES = {
    "Homeowner",
    "SalesDesigner",
    "PermitOfficer",
    "Manufacturer",
    "InstallManager",
    "Inspector",
}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Raises ERR_UNAUTHENTICATED.

    Stores (user_id, role) on flask.g for downstream use.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed_roles):
    """Authenticate then check the role is permitted. Raises ERR_FORBIDDEN_ROLE."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise errors.forbidden_role()
    return user_id, role
