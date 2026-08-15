"""Authentication and role authorization per PRD section 2.1."""

from flask import request

from .errors import ApiError

ROLES = {"DeskAdmin", "Editor", "Contributor", "FinanceUser", "VerificationEditor"}

ALL_ROLES = ["DeskAdmin", "Editor", "Contributor", "FinanceUser", "VerificationEditor"]


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or malformed X-User-Role / X-User-ID headers",
        )
    return uid, role


def require(allowed_roles):
    """Priority 1 (authentication) then priority 2 (role authorization)."""
    uid, role = auth()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint"
        )
    return uid, role


def require_owner(uid, owner_id):
    if uid != owner_id:
        raise ApiError(
            "ERR_NOT_OWNER",
            403,
            "Contributor may only act on their own resources",
        )
