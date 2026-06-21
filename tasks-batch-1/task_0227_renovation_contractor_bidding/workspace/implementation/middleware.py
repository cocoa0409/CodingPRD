"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

import errors

KNOWN_ROLES = {"Homeowner", "Contractor", "EscrowAgent", "PlatformAdmin", "Anonymous"}


def get_principal():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers missing/invalid.

    Headers: X-User-ID, X-User-Role. Role must be one of the five known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated("Missing or invalid X-User-ID / X-User-Role.")
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then enforce that the caller's role is in `allowed`.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) before
    ERR_FORBIDDEN (403) per validation priority.
    """
    user_id, role = get_principal()
    if role not in allowed:
        raise errors.forbidden("Role not permitted for this operation.")
    return user_id, role
