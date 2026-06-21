"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 priority 1-3).

Every request (except POST /members) must carry X-User-ID and X-User-Role.
X-User-Role must be one of the five recognized roles, otherwise the request is
ERR_UNAUTHENTICATED (401). If the role is recognized but not permitted for the
operation, ERR_FORBIDDEN_ROLE (403). Entity-backed ownership (Member/Distributor)
is enforced separately, after existence, via the helpers in services/.
"""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

CINEMA_MANAGER = "CinemaManager"
BOX_OFFICE_AGENT = "BoxOfficeAgent"
MEMBER = "Member"
DISTRIBUTOR = "Distributor"
ANONYMOUS = "Anonymous"

KNOWN_ROLES = {CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER, DISTRIBUTOR, ANONYMOUS}


def authenticate() -> str:
    """Priority 1: both headers present and X-User-Role is a known role.

    Returns the acting role; also stashes role + user_id on flask.g.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown X-User-Role")
    g.user_role = role
    g.user_id = user_id
    return role


def authorize(role: str, allowed_roles) -> None:
    """Priority 2: the acting role must be permitted for this operation."""
    if role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
