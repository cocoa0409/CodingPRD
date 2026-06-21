"""Auth header extraction, RBAC enforcement, and request body parsing helpers.

PRD §2.1: every request carries X-User-ID and X-User-Role. The four roles are
spelled exactly Customer, SalesAssociate, FittingSpecialist, ShopManager.
"""
from flask import request

import errors
from errors import fail

VALID_ROLES = {"Customer", "SalesAssociate", "FittingSpecialist", "ShopManager"}


def get_user_context():
    """Validate the user-context headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
             "Missing or invalid user context header")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2): role must be in the allowed set for this op."""
    if role not in allowed:
        fail(errors.ERR_INSUFFICIENT_PERMISSIONS,
             "Role not permitted for this operation")


def get_json_body():
    """Parse the JSON body; missing/empty body is treated as {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data
