"""Auth header extraction and role checking per PRD §2.1 / SCAFFOLD validations 1-2."""
from flask import request

from errors import ApiError

VALID_ROLES = {"Subscriber", "SupportAgent", "PartnerBillingOps", "PlatformAdmin"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or malformed X-User-Role header")
    return user_id, role


def require_roles(*roles):
    """Ensure the caller's role is in the allowed set. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted to call this endpoint")
    return user_id, role


def check_subscriber_ownership(user_id, role, account_id):
    """For Subscriber role, X-User-ID must equal the owning account_id (PRD §2.1).
    Opaque roles (SupportAgent, PartnerBillingOps, PlatformAdmin) skip this check."""
    if role == "Subscriber" and user_id != account_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Subscriber may only act on own account resources")
