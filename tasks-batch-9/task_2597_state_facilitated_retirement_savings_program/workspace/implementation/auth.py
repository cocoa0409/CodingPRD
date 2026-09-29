"""Identity, role and ownership checks (PRD 2.1 and 2.9 steps 1-4)."""
from flask import request

from errors import fail
from store import db

ROLES = ("ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Employer", "Participant")

ALL_ROLES = list(ROLES)
READ_ROLES_NO_EMPLOYER = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Participant"]
STAFF_AND_EMPLOYER = ["ProgramAdministrator", "ComplianceOfficer", "Employer"]


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_employer(self):
        return self.role == "Employer"

    @property
    def is_participant(self):
        return self.role == "Participant"


def header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value.strip()


def require(roles):
    """PRD 2.9: identity first (401), then role membership (403)."""
    user_id = header("X-User-ID")
    role = header("X-User-Role")
    if not user_id:
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if roles and role not in roles:
        fail("ERR_UNAUTHORIZED", "role %r may not perform this operation" % (role,))
    return Principal(user_id, role)


def require_clock_setter():
    """The logical-clock setter is the single endpoint exempt from ERR_UNAUTHENTICATED."""
    user_id = header("X-User-ID")
    role = header("X-User-Role")
    if role and role != "ProgramAdministrator":
        fail("ERR_UNAUTHORIZED", "only a ProgramAdministrator may move the logical clock")
    return Principal(user_id or "SYSTEM", role or "ProgramAdministrator")


# ------------------------------------------------------------------ ownership

def own_employer(principal, employer_id):
    """An Employer principal may only reach its own employer subtree."""
    if principal.is_employer and principal.user_id != employer_id:
        fail("ERR_FORBIDDEN_SCOPE", "this resource belongs to another employer")


def own_participant(principal, participant_id):
    if principal.is_participant and principal.user_id != participant_id:
        fail("ERR_FORBIDDEN_SCOPE", "this resource belongs to another participant")


def own_scope(principal, employer_id=None, participant_id=None):
    if employer_id is not None:
        own_employer(principal, employer_id)
    if participant_id is not None:
        own_participant(principal, participant_id)


# ------------------------------------------------------------------ lookups

def get_or_404(collection, row_id, error_id):
    if not isinstance(row_id, str) or not row_id:
        fail(error_id, "resource not found")
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(error_id, "resource not found")
    return row


def get_employer(employer_id):
    return get_or_404("employers", employer_id, "ERR_EMPLOYER_NOT_FOUND")


def get_participant(participant_id):
    return get_or_404("participants", participant_id, "ERR_PARTICIPANT_NOT_FOUND")


def get_enrollment(enrollment_id):
    return get_or_404("enrollments", enrollment_id, "ERR_ENROLLMENT_NOT_FOUND")


def get_account(account_id):
    return get_or_404("participant_accounts", account_id, "ERR_ACCOUNT_NOT_FOUND")


def get_remittance(remittance_id):
    return get_or_404("payroll_remittances", remittance_id, "ERR_REMITTANCE_NOT_FOUND")


def get_certification(cert_id):
    return get_or_404("exemption_certifications", cert_id, "ERR_EXEMPTION_NOT_FOUND")


def get_excess_case(case_id):
    return get_or_404("excess_cases", case_id, "ERR_EXCESS_CASE_NOT_FOUND")


def get_penalty(penalty_id):
    return get_or_404("penalty_assessments", penalty_id, "ERR_PENALTY_NOT_FOUND")


def get_transfer(transfer_id):
    return get_or_404("portability_transfers", transfer_id, "ERR_TRANSFER_NOT_FOUND")


def get_fund_option(option_id):
    return get_or_404("investment_options", option_id, "ERR_FUND_OPTION_NOT_FOUND")
