"""Auth context: X-User-ID / X-User-Role header validation and role gating."""

from flask import request

from errors import raise_err

ROLES = {"Servicer", "VendorAdmin", "Dispatcher", "FieldCrew", "QualityReviewer"}

ANY_ROLE = ["Servicer", "VendorAdmin", "Dispatcher", "FieldCrew", "QualityReviewer"]


def get_auth():
    """Validation tier 1: identity context."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and role must be a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    """Validation tier 2: caller role must be listed on the endpoint."""
    if role not in allowed:
        raise_err("ERR_FORBIDDEN_FOR_ROLE", "Caller role is not authorized for this endpoint")
