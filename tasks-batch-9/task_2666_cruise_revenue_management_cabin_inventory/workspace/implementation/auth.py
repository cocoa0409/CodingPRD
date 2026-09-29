"""Validation tiers 1-3 (headers, role recognition, role authorization) and the
ownership / segregation-of-duties tiers 7-8."""

from flask import request

from errors import ApiError

ROLES = (
    "RevenueManager",
    "ReservationAgent",
    "GroupSalesAgent",
    "PortOpsCoordinator",
    "Guest",
)

ALL_ROLES = list(ROLES)


def actor(*allowed_roles):
    """Tiers 1-3, in this exact order. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # Tier 1: both headers present and non-empty.
    if user_id is None or role is None or str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    # Tier 2: role recognised.
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    # Tier 3: role authorised for this endpoint.
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_booking_owner(role, user_id, booking):
    """Tier 7: a Guest may only act on their own booking."""
    if role == "Guest" and booking.get("guest_id") != user_id:
        raise ApiError("ERR_NOT_BOOKING_OWNER")


def require_four_eyes(user_id, block):
    """Tier 8: the creating agent may not sign the block definite."""
    if block.get("created_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
