"""Auth header extraction, role checking, grower ownership (PRD §2.1, §2.9)."""

from flask import request

from errors import raise_err

ROLES = {"Grower", "IntakeTechnician", "DryerOperator", "ClaimsAdjuster", "ElevatorManager"}


def get_ctx():
    """Priority 1: X-User-Role and X-User-ID present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        not isinstance(user_id, str)
        or not user_id.strip()
        or not isinstance(role, str)
        or role not in ROLES
    ):
        raise_err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role / X-User-ID headers")
    return {"user_id": user_id, "role": role}


def require_roles(ctx, roles):
    """Priority 2: role must be listed for the endpoint."""
    if ctx["role"] not in roles:
        raise_err("ERR_UNAUTHORIZED_ROLE", "Role not permitted on this endpoint")


def forbid_unless_owner(ctx, owner_customer_id):
    """Priority 3: a Grower may only touch their own account's resources."""
    if ctx["role"] == "Grower" and ctx["user_id"] != owner_customer_id:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Grower acting on a resource owned by another customer")
