"""Identifier resolution (PRD 2.5).  Path ids resolve left to right; body
foreign keys resolve afterwards in declaration order, reusing the same
per-collection not-found error family."""
from errors import ApiError
from store import db


def _get(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def season(identifier):
    return _get(db.seasons, identifier, "ERR_SEASON_NOT_FOUND")


def member(identifier):
    return _get(db.members, identifier, "ERR_MEMBER_NOT_FOUND")


def contract(identifier):
    return _get(db.contracts, identifier, "ERR_CONTRACT_NOT_FOUND")


def plan(identifier):
    return _get(db.plans, identifier, "ERR_PAYMENT_PLAN_NOT_FOUND")


def payment(identifier):
    return _get(db.payments, identifier, "ERR_TUITION_PAYMENT_NOT_FOUND")


def school(identifier):
    return _get(db.schools, identifier, "ERR_HOST_SCHOOL_NOT_FOUND")


def agreement(identifier):
    return _get(db.agreements, identifier, "ERR_FACILITY_AGREEMENT_NOT_FOUND")


def housing(identifier):
    return _get(db.housing, identifier, "ERR_HOUSING_ASSIGNMENT_NOT_FOUND")


def stop(identifier):
    return _get(db.stops, identifier, "ERR_TOUR_STOP_NOT_FOUND")


def booking(identifier):
    return _get(db.bookings, identifier, "ERR_SITE_BOOKING_NOT_FOUND")


def volunteer(identifier):
    return _get(db.volunteers, identifier, "ERR_VOLUNTEER_NOT_FOUND")


def staff(identifier):
    return _get(db.staff, identifier, "ERR_STAFF_ASSIGNMENT_NOT_FOUND")


def settlement(identifier):
    return _get(db.settlements, identifier, "ERR_SHOW_SETTLEMENT_NOT_FOUND")
