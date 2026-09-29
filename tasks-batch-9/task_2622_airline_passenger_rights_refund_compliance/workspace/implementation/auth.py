"""Caller identity, role authorisation (PRD 2.1) and passenger ownership."""

from flask import request

from errors import ApiError
from store import S

ROLES = (
    "ComplianceAdmin",
    "ComplianceOfficer",
    "OpsController",
    "RegulatorAuditor",
    "Passenger",
)

ADMIN = "ComplianceAdmin"
OFFICER = "ComplianceOfficer"
OPS = "OpsController"
AUDITOR = "RegulatorAuditor"
PASSENGER = "Passenger"

ALL_ROLES = list(ROLES)


def identity():
    """Step 1 and 2 of the precedence ladder (PRD 2.5)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(allowed):
    """Steps 1-2 then step 3 (endpoint authorisation)."""
    user_id, role = identity()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


# --------------------------------------------------------------------------
# Passenger ownership (PRD 2.1), evaluated BEFORE existence checks
# --------------------------------------------------------------------------

def own_passenger(user_id, role, passenger_id):
    if role == PASSENGER and passenger_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def own_booking(user_id, role, booking_id):
    """Ownership precedes existence: a missing booking is still a 403 for a passenger."""
    if role != PASSENGER:
        return
    booking = S.bookings.get(booking_id)
    if booking is None or booking["passenger_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def own_obligation(user_id, role, obligation_id):
    if role != PASSENGER:
        return
    obligation = S.refund_obligations.get(obligation_id)
    if obligation is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    booking = S.bookings.get(obligation["booking_id"])
    if booking is None or booking["passenger_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
