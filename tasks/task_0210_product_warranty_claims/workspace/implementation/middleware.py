"""Auth header extraction and RBAC, per PRD §2.1 / §2.10.

Headers (exact names from PRD §2.1):
  X-User-ID    — acting user identifier
  X-User-Role  — one of exactly: Owner, WarrantyAdmin, ClaimsProcessor

Order (PRD §2.10): authentication (401) is checked before authorization (403).
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

KNOWN_ROLES = {"Owner", "WarrantyAdmin", "ClaimsProcessor"}


def authenticate() -> None:
    """Populate g.user_role / g.user_id, enforcing presence + known role.

    Missing either header, or an unknown role value, -> ERR_UNAUTHENTICATED (401).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown X-User-Role")
    g.user_role = role
    g.user_id = user_id


def require_roles(allowed: Iterable[str]) -> None:
    """Authenticate, then enforce that the acting role is in `allowed` (else 403)."""
    authenticate()
    if g.user_role not in set(allowed):
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
