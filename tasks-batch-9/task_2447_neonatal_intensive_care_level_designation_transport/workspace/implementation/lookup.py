"""Path- and body-identifier resolution (PRD 2.10 bands 3 and 6)."""
from db import db
from errors import ApiError


def _get(collection, identifier, error_id):
    row = collection.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, 404)
    return row


def unit(identifier):
    return _get(db.units, identifier, "ERR_UNIT_NOT_FOUND")


def standard(identifier):
    return _get(db.standards, identifier, "ERR_STANDARD_NOT_FOUND")


def credential(identifier):
    return _get(db.credentials, identifier, "ERR_CREDENTIAL_NOT_FOUND")


def asset(identifier):
    return _get(db.assets, identifier, "ERR_ASSET_NOT_FOUND")


def review(identifier):
    return _get(db.reviews, identifier, "ERR_REVIEW_NOT_FOUND")


def referral(identifier):
    return _get(db.referrals, identifier, "ERR_REFERRAL_NOT_FOUND")


def reservation(identifier):
    return _get(db.reservations, identifier, "ERR_RESERVATION_NOT_FOUND")


def run(identifier):
    return _get(db.runs, identifier, "ERR_RUN_NOT_FOUND")


def admission(identifier):
    return _get(db.admissions, identifier, "ERR_ADMISSION_NOT_FOUND")


def batch(identifier):
    return _get(db.milk_batches, identifier, "ERR_MILK_BATCH_NOT_FOUND")


def escalation(identifier):
    return _get(db.escalations, identifier, "ERR_ESCALATION_NOT_FOUND")


def report(identifier):
    return _get(db.reports, identifier, "ERR_REPORT_NOT_FOUND")


def enrollment(identifier):
    return _get(db.enrollments, identifier, "ERR_ENROLLMENT_NOT_FOUND")
