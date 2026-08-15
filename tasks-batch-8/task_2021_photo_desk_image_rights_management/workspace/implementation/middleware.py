"""Auth middleware: header extraction, role validation, and RBAC checks."""

from flask import request
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"PhotoEditor", "Photographer", "RightsManager", "Archivist", "FinanceAdmin", "PlatformAdmin"}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role) on success.
    Raises ApiError(401) on missing/invalid headers.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header", 401)
    if role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, f"Invalid role: {role}", 401)
    return user_id, role


def require_role(role: str, allowed: set):
    """Raise 403 if the acting role is not in the allowed set."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, f"Role {role} is not permitted for this endpoint", 403)


def check_photographer_ownership(user_id: str, role: str, resource_photographer_id):
    """For Photographer role, verify entity-backed ownership."""
    if role == "Photographer":
        if resource_photographer_id != user_id:
            raise ApiError(ERR_FORBIDDEN, "Photographer may only access own resources", 403)
