"""Authentication, RBAC, ownership and segregation-of-duties (PRD 2.1, 2.9, 2.10)."""

from flask import request

from db import db
from errors import ApiError

CREDIT_OFFICER = "CreditOfficer"
TRADE_FINANCE_OFFICER = "TradeFinanceOfficer"
DOCUMENT_EXAMINER = "DocumentExaminer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
APPLICANT_USER = "ApplicantUser"
BENEFICIARY_USER = "BeneficiaryUser"
CORRESPONDENT_BANK = "CorrespondentBank"
SYSTEM_OPERATOR = "SystemOperator"

KNOWN_ROLES = frozenset([
    CREDIT_OFFICER,
    TRADE_FINANCE_OFFICER,
    DOCUMENT_EXAMINER,
    COMPLIANCE_OFFICER,
    APPLICANT_USER,
    BENEFICIARY_USER,
    CORRESPONDENT_BANK,
    SYSTEM_OPERATOR,
])


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_applicant(self):
        return self.role == APPLICANT_USER

    @property
    def is_beneficiary(self):
        return self.role == BENEFICIARY_USER

    @property
    def is_bank(self):
        return self.role == CORRESPONDENT_BANK


def authenticate():
    """Band 1: both headers must be present and non-empty, before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return Principal(str(user_id).strip(), str(role).strip())


def require(*allowed_roles):
    """Band 1 then band 2 (role membership). Returns the Principal."""
    principal = authenticate()
    if principal.role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    if allowed_roles and principal.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return principal


def not_party():
    raise ApiError("ERR_PRINCIPAL_NOT_PARTY")


def require_same_id(principal, expected_id):
    if principal.user_id != expected_id:
        not_party()


def segregation(principal, preparer_user_id):
    """PRD 2.10 -- four-eyes on approval, amendment issuance and screening review."""
    if preparer_user_id is not None and principal.user_id == preparer_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


# --------------------------------------------------------------------------
# existence resolution (PRD 2.7)
# --------------------------------------------------------------------------

_COLLECTION_ERRORS = (
    ("applicants", "ERR_APPLICANT_NOT_FOUND"),
    ("facilities", "ERR_FACILITY_NOT_FOUND"),
    ("banks", "ERR_BANK_NOT_FOUND"),
    ("beneficiaries", "ERR_BENEFICIARY_NOT_FOUND"),
    ("credits", "ERR_CREDIT_NOT_FOUND"),
    ("amendments", "ERR_AMENDMENT_NOT_FOUND"),
    ("presentations", "ERR_PRESENTATION_NOT_FOUND"),
    ("waivers", "ERR_WAIVER_REQUEST_NOT_FOUND"),
    ("claims", "ERR_SETTLEMENT_CLAIM_NOT_FOUND"),
    ("screenings", "ERR_SCREENING_CHECK_NOT_FOUND"),
)

COLLECTION_ERROR = dict(_COLLECTION_ERRORS)


def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def must_find(collection, row_id, error_id=None):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(error_id or COLLECTION_ERROR[collection])
    return row


def pending(collection, row_id, error_id=None):
    """Resolve a path id now (for band-2 ownership) but defer its 404 to band 3."""
    row = find(collection, row_id)
    if row is None:
        return None, ApiError(error_id or COLLECTION_ERROR[collection])
    return row, None


def raise_pending(deferred):
    if deferred is not None:
        raise deferred
