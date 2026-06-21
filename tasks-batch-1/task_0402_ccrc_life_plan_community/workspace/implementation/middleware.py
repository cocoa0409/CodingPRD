"""Auth header extraction + RBAC (PRD §2.1).

Headers (exact names from PRD §2.1): X-User-ID, X-User-Role.
Roles: FinanceOfficer, AdmissionsDirector, CareCoordinator, Resident.
Missing/malformed header -> ERR_MISSING_AUTH (401).
Valid request, role not permitted -> ERR_FORBIDDEN_ROLE (403).
"""
from __future__ import annotations

from typing import Optional

from flask import g, request

from errors import err

ALLOWED_ROLES = {"FinanceOfficer", "AdmissionsDirector", "CareCoordinator", "Resident"}


def authenticate():
    """Validate the two mandatory auth headers; store identity on g.

    Both X-User-ID and X-User-Role must be present, non-empty, and X-User-Role
    must be one of the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        err("ERR_MISSING_AUTH", "Missing or malformed X-User-ID header")
    if not role or not role.strip():
        err("ERR_MISSING_AUTH", "Missing or malformed X-User-Role header")
    if role not in ALLOWED_ROLES:
        err("ERR_MISSING_AUTH", "Unrecognized X-User-Role header")
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed):
    """After authentication, ensure the caller's role is permitted."""
    if g.user_role not in set(allowed):
        err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
