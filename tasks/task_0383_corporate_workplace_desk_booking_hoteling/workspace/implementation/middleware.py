"""Auth header extraction and role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. The four recognized roles are
FacilityManager, Employee, Receptionist, Analyst. Missing/blank header or an
unknown role -> ERR_UNAUTHENTICATED (401). Well-formed but not permitted for the
operation -> ERR_FORBIDDEN (403).
"""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALLOWED_ROLES = {"FacilityManager", "Employee", "Receptionist", "Analyst"}


def authenticate():
    """Validate presence of headers + recognized role. Populates g.user_role /
    g.user_id. Raises ERR_UNAUTHENTICATED on any failure (priority 1)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or user_id is None or user_id == "":
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or blank X-User-ID / X-User-Role")
    if role not in ALLOWED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown role value")
    g.user_role = role
    g.user_id = user_id


def require_role(*allowed):
    """Authorize the operation against the acting role (priority 2). Authenticates
    first if not already done. Raises ERR_FORBIDDEN if the role is not allowed."""
    authenticate()
    if g.user_role not in set(allowed):
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
