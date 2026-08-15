"""Auth header extraction, role checking, borrower ownership (PRD 2.1/2.9)."""

from flask import request

from errors import ApiError, ERR_AUTH_HEADER, ERR_FORBIDDEN, ERR_NOT_OWNER

ALL_ROLES = (
    "ComplianceOfficer",
    "EscrowAnalyst",
    "DisbursementProcessor",
    "PayeeVerifier",
    "InsuranceSpecialist",
    "Borrower",
)
ROLE_SET = set(ALL_ROLES)


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not isinstance(uid, str) or not uid.strip():
        raise ApiError(ERR_AUTH_HEADER, 400, "Missing or malformed X-User-ID")
    if not isinstance(role, str) or role not in ROLE_SET:
        raise ApiError(ERR_AUTH_HEADER, 400, "Missing or malformed X-User-Role")
    return uid, role


def require_roles(*roles):
    """Priority 1 (headers) then priority 2 (role authorization)."""
    uid, role = get_auth()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not authorized for this endpoint" % role)
    return uid, role


def any_role():
    return require_roles(*ALL_ROLES)


def check_borrower_owner(uid, owning_loan_id):
    """Priority 3: Borrower ownership — X-User-ID must equal owning Loan id."""
    if uid != owning_loan_id:
        raise ApiError(ERR_NOT_OWNER, 403, "Borrower does not own this resource")
