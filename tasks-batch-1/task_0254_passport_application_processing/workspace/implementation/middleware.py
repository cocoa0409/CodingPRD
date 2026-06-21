"""Auth header extraction and RBAC enforcement (PRD §2.1 / scaffold §1.7).

Auth headers: X-User-ID, X-User-Role. Roles are exactly: Applicant,
AcceptanceAgent, Adjudicator. Two endpoints are anonymous: POST /applicants
and POST /_clock/set_current_utc.
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

VALID_ROLES = {"Applicant", "AcceptanceAgent", "Adjudicator"}


def authenticate() -> None:
    """Validate the two auth headers. Populates g.user_role / g.user_id.

    Raises ERR_UNAUTHENTICATED (401) when either header is missing or the role
    value is not one of the three recognized roles.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unrecognized X-User-Role value")
    g.user_role = role
    g.user_id = user_id


def authorize(allowed_roles: Iterable[str]) -> None:
    """Authorization check (ERR_FORBIDDEN, 403) given the authenticated role."""
    role = getattr(g, "user_role", None)
    if role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")


def require_auth(allowed_roles: Iterable[str]) -> None:
    """Auth (priority 1) then RBAC (priority 2) in order."""
    authenticate()
    authorize(allowed_roles)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
