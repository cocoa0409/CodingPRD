"""Auth middleware per PRD section 2.1 and scaffold validations p1/p2.

Headers: X-User-ID (identity) and X-User-Role (declared role name).
- Missing header or undeclared role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
- Role not authorized on an endpoint -> ERR_INSUFFICIENT_PERMISSIONS (403)

Shipper is entity-backed: X-User-ID is the id of the acting Shipper entity and
ownership-gated operations compare resource shipper_id to X-User-ID. All other
roles are opaque operator identifiers.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    HTTP_STATUS,
)

ROLES = {
    "Shipper",
    "BookingCoordinator",
    "DocumentationOfficer",
    "ComplianceOfficer",
    "FinanceController",
    "ClaimsAdjuster",
    "OperationsManager",
}

ALL_ROLES = tuple(sorted(ROLES))


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers (validation band 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or user_id.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (band 1), then enforce role membership (band 2).

    The "Any" pseudo-role on GET endpoints means every declared role may call
    the endpoint; pass ALL_ROLES for those.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def check_shipper_ownership(role: str, user_id: str, owner_shipper_id: str) -> None:
    """Band-2 ownership predicate for the entity-backed Shipper role."""
    if role == "Shipper" and user_id != owner_shipper_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Shipper may only act on its own resources",
        )
