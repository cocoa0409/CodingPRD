"""Auth header extraction and role checking (PRD 2.1, precedence 1-3)."""

from functools import wraps

from flask import request

import db
import errors
from errors import fail

APPLICANT = "Applicant"
CONTRACTOR = "Contractor"
INTAKE_SPECIALIST = "IntakeSpecialist"
REHAB_SPECIALIST = "RehabSpecialist"
INSPECTOR = "Inspector"
LOAN_OFFICER = "LoanOfficer"
PROGRAM_MANAGER = "ProgramManager"

ALL_ROLES = (
    APPLICANT,
    CONTRACTOR,
    INTAKE_SPECIALIST,
    REHAB_SPECIALIST,
    INSPECTOR,
    LOAN_OFFICER,
    PROGRAM_MANAGER,
)

STAFF_ROLES = (
    INTAKE_SPECIALIST,
    REHAB_SPECIALIST,
    INSPECTOR,
    LOAN_OFFICER,
    PROGRAM_MANAGER,
)


def user_id():
    return request.headers.get("X-User-ID") or ""


def user_role():
    return request.headers.get("X-User-Role") or ""


def roles(*allowed):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN_ROLE)."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            role = user_role()
            if not role or role not in ALL_ROLES:
                fail(errors.ERR_UNAUTHENTICATED)
            if role not in allowed:
                fail(errors.ERR_FORBIDDEN_ROLE)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def _application_of_loan(loan):
    return db.applications.get(loan["application_id"]) if loan else None


def scope_application(application_id):
    """Priority 3 for reading one rehabilitation application.

    The check never discloses whether the row exists: an Applicant addressing a
    row that is not theirs — including one that does not exist — is refused with
    ERR_OWNERSHIP_MISMATCH.
    """
    if user_role() != APPLICANT:
        return
    row = db.applications.get(application_id)
    if row is None or row.get("applicant_id") != user_id():
        fail(errors.ERR_OWNERSHIP_MISMATCH)


def scope_loan(loan_id):
    """Priority 3 for reading one loan (transitive through the case)."""
    if user_role() != APPLICANT:
        return
    loan = db.loans.get(loan_id)
    application = _application_of_loan(loan)
    if application is None or application.get("applicant_id") != user_id():
        fail(errors.ERR_OWNERSHIP_MISMATCH)


def scope_complaint(complaint_id):
    """Priority 3 for reading one complaint case."""
    role = user_role()
    if role not in (APPLICANT, CONTRACTOR):
        return
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        fail(errors.ERR_OWNERSHIP_MISMATCH)
    if role == CONTRACTOR:
        if complaint.get("contractor_id") != user_id():
            fail(errors.ERR_OWNERSHIP_MISMATCH)
        return
    application = db.applications.get(complaint.get("application_id"))
    if application is None or application.get("applicant_id") != user_id():
        fail(errors.ERR_OWNERSHIP_MISMATCH)


def scope_body_contractor(body):
    """Priority 3 for submitting a bid / creating a draw request."""
    if user_role() != CONTRACTOR:
        return
    if not isinstance(body, dict):
        return
    supplied = body.get("contractor_id")
    if supplied is None:
        return
    if supplied != user_id():
        fail(errors.ERR_OWNERSHIP_MISMATCH)
