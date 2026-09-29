"""Existence resolution (PRD §2.7, checks 4 and 5) and applicant read scoping."""
import db
from constants import ROLE_APPLICANT
from errors import (
    ERR_APPLICANT_NOT_FOUND, ERR_APPLICATION_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND, ERR_CREDIT_AWARD_NOT_FOUND,
    ERR_DISCIPLINARY_RECORD_NOT_FOUND, ERR_EVALUATION_NOT_FOUND,
    ERR_EVALUATOR_NOT_FOUND, ERR_LICENSE_NOT_FOUND, ERR_OWNERSHIP_VIOLATION,
    ERR_PERMIT_NOT_FOUND, ERR_PROFESSION_NOT_FOUND, ERR_TRAINING_RECORD_NOT_FOUND,
    fail,
)


def _get(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "The referenced resource does not exist.")
    return row


def profession(row_id):
    return _get(db.professions, row_id, ERR_PROFESSION_NOT_FOUND)


def applicant(row_id):
    return _get(db.applicants, row_id, ERR_APPLICANT_NOT_FOUND)


def credential(row_id):
    return _get(db.credentials, row_id, ERR_CREDENTIAL_NOT_FOUND)


def application(row_id):
    return _get(db.applications, row_id, ERR_APPLICATION_NOT_FOUND)


def evaluation(row_id):
    return _get(db.evaluations, row_id, ERR_EVALUATION_NOT_FOUND)


def training_record(row_id):
    return _get(db.training_records, row_id, ERR_TRAINING_RECORD_NOT_FOUND)


def credit_award(row_id):
    return _get(db.credit_awards, row_id, ERR_CREDIT_AWARD_NOT_FOUND)


def permit(row_id):
    return _get(db.permits, row_id, ERR_PERMIT_NOT_FOUND)


def license_row(row_id):
    return _get(db.licenses, row_id, ERR_LICENSE_NOT_FOUND)


def evaluator(row_id):
    return _get(db.evaluators, row_id, ERR_EVALUATOR_NOT_FOUND)


def assignment(row_id):
    return _get(db.assignments, row_id, ERR_ASSIGNMENT_NOT_FOUND)


def disciplinary_record(row_id):
    return _get(db.disciplinary_records, row_id, ERR_DISCIPLINARY_RECORD_NOT_FOUND)


# ---------------------------------------------------------------------------
def require_applicant_ownership(role, user_id, applicant_id):
    """Check 6: an Applicant may only act on, or read, its own rows."""
    if role == ROLE_APPLICANT and user_id != applicant_id:
        fail(ERR_OWNERSHIP_VIOLATION,
             "An Applicant may only access their own records.")
