"""Auth middleware: identity headers, role authorization, grower ownership."""

from flask import request

import db
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_GROWER_OWNERSHIP_MISMATCH,
)

ROLES = {"DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"}
GROWER = "Grower"


def authenticate(allowed_roles):
    """Priority 1 (headers) then priority 2 (role authorization).
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role


def check_grower_ownership(user_id, role, grower_id):
    """Priority 3: a Grower caller may only act on own resources."""
    if role == GROWER and grower_id != user_id:
        raise ApiError(
            ERR_GROWER_OWNERSHIP_MISMATCH,
            403,
            "grower may only act on own resources",
        )


def order_of_line(line):
    return db.get("orders", line["order_id"]) if line else None


def grower_id_of_order(order):
    return order["grower_id"] if order else None
