"""Auth header extraction and RBAC (PRD §2.1, §2.5)."""
from flask import request

from errors import err

VALID_ROLES = {
    "CatalogAdmin",
    "Patient",
    "OrderingPhysician",
    "PhlebotomyTech",
    "LabTech",
}


def require_context():
    """Validate X-User-ID and X-User-Role headers (priority 1).

    Both headers must be present, non-empty, and X-User-Role must be one of the
    five recognized roles; otherwise ERR_MISSING_USER_CONTEXT (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(allowed_roles):
    """priority 1 (context) then priority 2 (role permission)."""
    user_id, role = require_context()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
    return user_id, role
