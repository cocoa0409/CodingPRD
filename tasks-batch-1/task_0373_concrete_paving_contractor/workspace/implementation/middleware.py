"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.6, scaffold §1.7)."""
from flask import request, g

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"Estimator", "ProjectManager", "FinanceOfficer", "Inspector"}
ALL_ROLES = VALID_ROLES


def authenticate():
    """Validate the X-User-ID / X-User-Role headers. Sets g.user_id and g.role.

    Per PRD §2.1: a request missing either header is ERR_UNAUTHENTICATED (401).
    The role value itself is not checked here; an unknown role simply fails the
    per-endpoint RBAC check (ERR_FORBIDDEN_ROLE).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed_roles):
    """Enforce that g.role is in the allowed set, else ERR_FORBIDDEN_ROLE (403)."""
    if g.role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, f"Role {g.role!r} is not permitted for this operation")
