"""Authentication, role authorisation and ownership scoping (PRD 2.1, ladder ranks 1-5)."""

from flask import request

import store
from errors import ApiError

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
REVENUE_MANAGER = "RevenueManager"
COMPLIANCE_OFFICER = "ComplianceOfficer"
REGULATORY_LIAISON = "RegulatoryLiaison"
CHANNEL_OPERATOR = "ChannelOperator"
GUEST_SERVICES_AGENT = "GuestServicesAgent"
GUEST = "Guest"

ROLES = (
    PLATFORM_ADMIN, REVENUE_MANAGER, COMPLIANCE_OFFICER, REGULATORY_LIAISON,
    CHANNEL_OPERATOR, GUEST_SERVICES_AGENT, GUEST,
)

# Every role (used by the reads a Guest may also perform).
ALL_ROLES = list(ROLES)
# Every operator role — the six roles that are not the staying Guest.
OPERATORS = [
    PLATFORM_ADMIN, REVENUE_MANAGER, COMPLIANCE_OFFICER, REGULATORY_LIAISON,
    CHANNEL_OPERATOR, GUEST_SERVICES_AGENT,
]


def identity():
    """Rank 1 header presence and rank 2 role recognition."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "%s is not a recognised role." % role)
    return user_id, role


def require(allowed_roles):
    """Ranks 1-3. Returns (user_id, role) for an authorised caller."""
    user_id, role = identity()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)
    return user_id, role


# ------------------------------------------------------------------ rank 4

def acting_channel(user_id):
    """The Channel a ChannelOperator is acting as, or 403 when the id is unknown."""
    channel = store.channels.get(user_id)
    if channel is None:
        raise ApiError(
            "ERR_CHANNEL_OWNERSHIP_REQUIRED",
            "X-User-ID must be an existing Channel identifier for a ChannelOperator.",
        )
    return channel


def channel_owns(user_id, channel_id):
    """Rank 4 ownership comparison against a resource's channel_id."""
    acting_channel(user_id)
    if channel_id != user_id:
        raise ApiError(
            "ERR_CHANNEL_OWNERSHIP_REQUIRED",
            "The addressed resource belongs to another channel.",
        )


# ------------------------------------------------------------------ rank 5

def acting_booking(user_id):
    """The Booking a Guest is acting as, or 403 when the id is unknown."""
    booking = store.bookings.get(user_id)
    if booking is None:
        raise ApiError(
            "ERR_BOOKING_OWNERSHIP_REQUIRED",
            "X-User-ID must be an existing Booking identifier for a Guest.",
        )
    return booking


def booking_owns(user_id, booking_id):
    """Rank 5 ownership comparison against the owning booking of a resource."""
    acting_booking(user_id)
    if booking_id != user_id:
        raise ApiError(
            "ERR_BOOKING_OWNERSHIP_REQUIRED",
            "The addressed resource does not belong to the acting booking.",
        )
