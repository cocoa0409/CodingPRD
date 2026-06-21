"""Auth header extraction and RBAC checks (PRD §2.1, §2.9)."""
from __future__ import annotations

from typing import Optional

from flask import g, request

from errors import APIError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

# Exactly five recognized roles (PRD §2.1).
ALLOWED_ROLES = {"FrontDesk", "Provider", "Biller", "QualityAnalyst", "Patient"}


def authenticate() -> None:
    """Priority 1: both headers present and well-formed (PRD §2.1).

    X-User-ID identifies the acting user; X-User-Role declares the role.
    A missing or malformed (unknown-role) header yields ERR_UNAUTHENTICATED (401).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ALLOWED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or malformed authentication headers")
    g.user_role = role
    g.user_id = user_id


def authorize(allowed_roles) -> None:
    """Priority 2: acting role is permitted for this operation (PRD §2.1)."""
    if g.user_role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this operation")


def require(allowed_roles):
    """Run auth (401) then role (403) in order. Call at the top of every handler."""
    authenticate()
    authorize(allowed_roles)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
