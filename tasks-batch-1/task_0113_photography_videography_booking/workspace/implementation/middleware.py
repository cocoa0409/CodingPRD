"""Auth header extraction and role checking (PRD §2.1, §2.7).

Every request carries two mandatory headers: X-User-ID and X-User-Role.
The four recognized roles, spelled exactly: Anonymous, Client, Photographer,
StudioAdmin. Missing/malformed header -> ERR_UNAUTHENTICATED (401). Well-formed
but not permitted for the endpoint -> ERR_FORBIDDEN_ROLE (403).
"""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

HEADER_ROLE = "X-User-Role"
HEADER_USER_ID = "X-User-ID"

ROLE_ANONYMOUS = "Anonymous"
ROLE_CLIENT = "Client"
ROLE_PHOTOGRAPHER = "Photographer"
ROLE_STUDIO_ADMIN = "StudioAdmin"

ALL_ROLES = {ROLE_ANONYMOUS, ROLE_CLIENT, ROLE_PHOTOGRAPHER, ROLE_STUDIO_ADMIN}


def authenticate() -> None:
    """Priority 1 (PRD §2.7): both headers present and well-formed.

    A request that omits either header, or supplies a role outside the
    recognized set, is rejected with ERR_UNAUTHENTICATED.
    """
    role = request.headers.get(HEADER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID / X-User-Role")
    if role not in ALL_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, f"Unknown role: {role}")
    g.user_role = role
    g.user_id = user_id


def authorize(allowed_roles) -> None:
    """Priority 2 (PRD §2.7): the acting role must be permitted for the
    endpoint. Otherwise ERR_FORBIDDEN_ROLE."""
    if g.user_role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")


def require_auth(allowed_roles):
    """Run auth (priority 1) then role authorization (priority 2)."""
    authenticate()
    authorize(allowed_roles)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
