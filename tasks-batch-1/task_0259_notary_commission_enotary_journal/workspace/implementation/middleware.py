"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.7).

Headers: X-User-ID (acting principal), X-User-Role (capacity). Known roles:
CommissionAuthority, Notary, Anonymous. Missing header or unknown role ->
ERR_UNAUTHENTICATED (401). Role not permitted for the op -> ERR_UNAUTHORIZED.
"""
from functools import wraps

from flask import request, g

from errors import err

KNOWN_ROLES = {"CommissionAuthority", "Notary", "Anonymous"}


def extract_identity():
    """Read auth headers into flask.g. Does not raise; checks happen per-route."""
    g.user_id = request.headers.get("X-User-ID")
    g.user_role = request.headers.get("X-User-Role")


def require_auth():
    """Both headers present and X-User-Role a known role (priority 1)."""
    if not g.get("user_id") or not g.get("user_role"):
        raise err("ERR_UNAUTHENTICATED", "Missing authentication headers")
    if g.user_role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role")


def require_role(*allowed):
    """Acting role must be in the permitted set for this op (priority 2)."""
    if g.get("user_role") not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def endpoint(roles, exempt_auth=False):
    """Decorator: run auth + RBAC before the handler.

    roles: tuple of role names permitted for this endpoint.
    exempt_auth: True for the public endpoints (create jurisdiction, register
    notary, clock endpoints) that do not require the auth headers.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not exempt_auth:
                require_auth()
                require_role(*roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
