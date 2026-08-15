"""Auth middleware: identity headers, role authorization, buyer ownership.

Validation tiers (PRD section 2.10):
  1. header context  -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. role authorization -> ERR_FORBIDDEN_ROLE (403)
  5. buyer ownership -> ERR_NOT_RESOURCE_OWNER (403)
"""

from flask import request

from constants import ALL_ROLES, ROLE_BUYER
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
)


def authenticate(allowed_roles):
    """Priority 1 (headers present, declared role) then priority 2 (role
    authorized for the endpoint). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in ALL_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            f"unrecognized role: {role}",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role


def require_agreement_owner(agreement, user_id, role):
    """Priority 5: a Buyer caller may only act on their own agreement.
    Staff roles are opaque and exempt (PRD section 2.1)."""
    if role == ROLE_BUYER and agreement["buyer_id"] != user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "buyer may only act on their own agreement",
        )
