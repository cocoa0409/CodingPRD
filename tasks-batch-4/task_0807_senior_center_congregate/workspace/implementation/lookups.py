"""Existence lookups returning entity-specific not-found errors (PRD 2.6 step 3)."""
from store import db
from core import err


def _get(coll, ident, error_id):
    rec = coll.get(ident)
    if rec is None:
        raise err(error_id)
    return rec


def get_participant(i):
    return _get(db.participants, i, "ERR_PARTICIPANT_NOT_FOUND")


def get_grant(i):
    return _get(db.grants, i, "ERR_GRANT_NOT_FOUND")


def get_donation(i):
    return _get(db.donations, i, "ERR_DONATION_NOT_FOUND")


def get_funded_service(i):
    return _get(db.funded_services, i, "ERR_FUNDED_SERVICE_NOT_FOUND")


def get_room(i):
    return _get(db.rooms, i, "ERR_ROOM_NOT_FOUND")


def get_session(i):
    return _get(db.sessions, i, "ERR_SESSION_NOT_FOUND")


def get_signup(i):
    return _get(db.signups, i, "ERR_SIGNUP_NOT_FOUND")


def get_vehicle(i):
    return _get(db.vehicles, i, "ERR_VEHICLE_NOT_FOUND")


def get_transport(i):
    return _get(db.transports, i, "ERR_TRANSPORT_NOT_FOUND")


def get_service_day(i):
    return _get(db.service_days, i, "ERR_SERVICE_DAY_NOT_FOUND")


def get_reservation(i):
    return _get(db.reservations, i, "ERR_RESERVATION_NOT_FOUND")


def get_program(i):
    return _get(db.programs, i, "ERR_PROGRAM_NOT_FOUND")


def get_enrollment(i):
    return _get(db.enrollments, i, "ERR_ENROLLMENT_NOT_FOUND")
