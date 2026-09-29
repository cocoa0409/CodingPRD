"""Shared state and fiscal guards, applied in the order of PRD 2.8."""

from errors import ApiError
from svc_ledger import available_points


def require_state(row, allowed, field="status"):
    if row[field] not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "%s '%s' is not a declared origin state for this transition."
            % (field, row[field]),
        )
    return row


def require_account_open(account):
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED", "Account '%s' is closed." % account["id"])
    return account


def require_not_locked(account):
    if account["fraud_posture"] == "LOCKED":
        raise ApiError(
            "ERR_ACCOUNT_POSTURE_LOCKED",
            "Account '%s' has a LOCKED fraud posture." % account["id"],
        )
    return account


def require_offer_bookable(offer):
    if offer["status"] != "OPEN":
        raise ApiError(
            "ERR_OFFER_NOT_BOOKABLE",
            "Offer '%s' is %s and is not bookable." % (offer["id"], offer["status"]),
        )
    return offer


def require_agreement_active(agreement):
    if agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVE",
            "Partner agreement '%s' is %s, not ACTIVE." % (agreement["id"], agreement["status"]),
        )
    return agreement


def require_agency_active(agency):
    if agency["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGENCY_SUSPENDED",
            "Agency '%s' is suspended." % agency["id"],
        )
    return agency


def require_in_parity(offer):
    if offer["parity_status"] != "IN_PARITY":
        raise ApiError(
            "ERR_OFFER_OUT_OF_PARITY",
            "Offer '%s' is out of parity." % offer["id"],
        )
    return offer


def require_seat(offer):
    if offer["seats_committed"] >= offer["portal_seats"]:
        raise ApiError(
            "ERR_SEAT_UNAVAILABLE",
            "Offer '%s' has no portal seat available." % offer["id"],
        )
    return offer


def require_available_points(account, points):
    if points > available_points(account):
        raise ApiError(
            "ERR_INSUFFICIENT_POINTS",
            "Account '%s' has insufficient available points." % account["id"],
        )
    return account
