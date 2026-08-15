"""Auth header extraction and role checking per PRD section 2.1."""

from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "Paralegal",
    "AssociateAttorney",
    "PartnerAttorney",
    "ClientContact",
    "WatchService",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(*allowed):
    """Authenticate and require the caller's role to be in the endpoint role list."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


def enforce_client_scope(user_id, role, client_id):
    """ClientContact may only access resources whose client_id == X-User-ID."""
    if role == "ClientContact" and client_id != user_id:
        raise_error(ERR_FORBIDDEN, "ClientContact may only access resources of their own client")
