"""Auth header extraction and role checking (PRD §2.1 / SCAFFOLD §1.4, §1.7)."""
from flask import request

import errors

# Exactly four roles, spelled precisely (PRD §2.1).
KNOWN_ROLES = {"Customer", "Dispatcher", "Technician", "ServiceManager"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers.

    Both must be present and X-User-Role must be a known role, else
    ERR_UNAUTHENTICATED (401). Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid auth headers")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) when the acting role is not permitted."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
