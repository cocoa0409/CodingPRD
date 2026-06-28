"""Auth header extraction and RBAC role checking (PRD §2.1, §2.7)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"Dispatcher", "FieldTech", "Customer", "BillingAdmin"}


def get_identity():
    """Return (user_id, role) after validating presence/well-formedness.

    Raises ERR_MISSING_AUTH_HEADER (401) when a header is missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_MISSING_AUTH_HEADER", "Missing X-User-ID or X-User-Role")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER", "Malformed X-User-ID")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER", "Malformed X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED (403) when role not in allowed set."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")
