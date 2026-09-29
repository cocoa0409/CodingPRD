"""Existence resolution (validation ladder positions 4 and 5)."""

from errors import ApiError
from store import db


def _get(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id, "Identifier not found.")
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id, "Identifier %s not found." % identifier)
    return record


def school(identifier):
    return _get(db.schools, identifier, "ERR_SCHOOL_NOT_FOUND")


def psychologist(identifier):
    return _get(db.psychologists, identifier, "ERR_PSYCHOLOGIST_NOT_FOUND")


def referral(identifier):
    return _get(db.referrals, identifier, "ERR_REFERRAL_NOT_FOUND")


def evaluation(identifier):
    return _get(db.evaluations, identifier, "ERR_EVALUATION_NOT_FOUND")


def instrument(identifier):
    return _get(db.instruments, identifier, "ERR_INSTRUMENT_NOT_FOUND")


def order(identifier):
    return _get(db.orders, identifier, "ERR_ORDER_NOT_FOUND")


def exclusion(identifier):
    return _get(db.exclusions, identifier, "ERR_EXCLUSION_NOT_FOUND")


def meeting(identifier):
    return _get(db.meetings, identifier, "ERR_MEETING_NOT_FOUND")


def breach(identifier):
    return _get(db.breaches, identifier, "ERR_BREACH_NOT_FOUND")


def seat_of_instrument(instrument_record, seat_id):
    record = db.seats.get(seat_id) if isinstance(seat_id, str) else None
    if record is None or record["instrument_id"] != instrument_record["id"]:
        raise ApiError("ERR_SEAT_NOT_FOUND", "Seat %s not found on this instrument." % seat_id)
    return record
