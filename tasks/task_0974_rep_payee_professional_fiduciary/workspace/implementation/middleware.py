"""Auth + RBAC middleware helpers.

Two headers on every request:
  X-User-ID   — opaque operator id (or Conservator.id for ConservatorOfficer)
  X-User-Role — one of the five declared roles
"""

from flask import request

from errors import (
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    err,
)

ROLES = {
    "FiduciaryAdmin",
    "CaseManager",
    "FinancialOfficer",
    "ConservatorOfficer",
    "ComplianceAuditor",
}


def get_auth():
    """Return (user_id, role). Raise ApiError(401) if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, 401, "Missing or invalid X-User-ID / X-User-Role")
    return user_id, role


def require_roles(*allowed):
    """Authenticate then check role membership."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return user_id, role
