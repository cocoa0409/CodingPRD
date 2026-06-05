"""Auth header extraction and RBAC.

PRD §2.1: every request must include X-User-ID (acting user) and X-User-Role
(operational capacity). Missing either header, or an unrecognized role, yields
ERR_UNAUTHENTICATED. A valid-but-unpermitted role yields ERR_FORBIDDEN_ROLE.

The five recognized roles, spelled precisely (PRD §2.1):
    Customer, Estimator, Dispatcher, ClaimsAdjuster, PlatformAdmin
"""
from flask import request

from errors import err

ROLES = {"Customer", "Estimator", "Dispatcher", "ClaimsAdjuster", "PlatformAdmin"}


def authenticate():
    """Validate the auth headers (validation priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (validation priority 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation." % role)
