"""Auth header extraction, role checking, passenger ownership (PRD §2.1)."""

from flask import request

import errors
from db import db

ROLES = {
    "OpsController",
    "DutyManager",
    "ReaccommodationAgent",
    "CrewScheduler",
    "FinanceProcessor",
    "OpsAdmin",
    "Passenger",
}

ALL_ROLES = [
    "OpsController",
    "DutyManager",
    "ReaccommodationAgent",
    "CrewScheduler",
    "FinanceProcessor",
    "OpsAdmin",
    "Passenger",
]


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_passenger(self):
        return self.role == "Passenger"


def authenticate():
    """Validate X-User-ID / X-User-Role headers. Returns a Caller."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        errors.raise_error(errors.ERR_UNAUTHENTICATED,
                           "Missing or malformed X-User-ID / X-User-Role headers")
    if not role or role not in ROLES:
        errors.raise_error(errors.ERR_UNAUTHENTICATED,
                           "Missing or malformed X-User-ID / X-User-Role headers")
    return Caller(user_id.strip(), role)


def require_role(caller, allowed):
    if caller.role not in allowed:
        errors.raise_error(errors.ERR_FORBIDDEN_ROLE,
                           "Role %s is not permitted for this endpoint" % caller.role)


def check_booking_ownership(caller, booking):
    """Passenger role may only touch resources whose booking chain belongs to them."""
    if caller.is_passenger and booking["passenger_id"] != caller.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN_OWNERSHIP,
                           "Passenger may only act on their own bookings")


def booking_of_case(case):
    return db.bookings.get(case["booking_id"])


def booking_of_option(option):
    case = db.reaccommodation_cases.get(option["case_id"])
    if case is None:
        return None
    return db.bookings.get(case["booking_id"])
