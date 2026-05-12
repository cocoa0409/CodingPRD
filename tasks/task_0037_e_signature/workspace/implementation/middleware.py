"""Auth header extraction and role checking per PRD §2.1."""

from functools import wraps

from flask import g, request

from errors import APIError, unauthenticated, forbidden


VALID_ROLES = {
    "TemplateAdmin",
    "ContractInitiator",
    "Signer",
    "EvidenceArchivist",
    "PlatformAdmin",
    "SystemSweeper",
}


def extract_auth():
    """Pull X-User-ID and X-User-Role from the request, raising on failure.

    Stores them on flask.g for downstream use.
    """
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    user_id = user_id.strip() if isinstance(user_id, str) else ""
    role = role.strip() if isinstance(role, str) else ""
    if not user_id or not role:
        raise unauthenticated()
    if role not in VALID_ROLES:
        # Unknown role => not authorized for any endpoint
        raise unauthenticated("Unknown role: %s" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce that the authenticated role is in the allowed set."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
