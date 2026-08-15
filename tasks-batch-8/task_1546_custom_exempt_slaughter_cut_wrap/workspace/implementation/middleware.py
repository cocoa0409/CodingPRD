"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD validations 1-2)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_FORBIDDEN, raise_error

ROLES = ("Customer", "PlantOperator", "PlantManager")

ALL_ROLES = ROLES
STAFF = ("PlantOperator", "PlantManager")


def require_auth():
    """Validate X-User-Role / X-User-ID headers and return (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(allowed_roles):
    """Require the caller's role to be listed in allowed_roles."""
    user_id, role = require_auth()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, "Role not allowed on this endpoint")
    return user_id, role
