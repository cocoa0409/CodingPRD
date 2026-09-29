"""Authentication and authorisation (PRD 2.1, ladder priorities 1, 2 and 4)."""

from flask import request

from db import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

CREDIT_OFFICER = "CreditOfficer"
COLLATERAL_ANALYST = "CollateralAnalyst"
WIRE_OPERATOR = "WireOperator"
BORROWER = "Borrower"
CUSTODIAN = "Custodian"
INVESTOR = "Investor"

ALL_ROLES = (
    CREDIT_OFFICER, COLLATERAL_ANALYST, WIRE_OPERATOR, BORROWER, CUSTODIAN, INVESTOR,
)

# Entity-backed roles: X-User-ID is a resource identifier of the backing entity.
_BACKING = {
    BORROWER: "facilities",
    CUSTODIAN: "custodians",
    INVESTOR: "investors",
}


def require_auth(allowed_roles):
    """Priority 1 then priority 2.  Runs before any path resolution."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not authorised for this endpoint." % role)
    backing = _BACKING.get(role)
    if backing is not None:
        if user_id not in getattr(db, backing):
            raise ApiError(
                "ERR_UNAUTHORIZED",
                "The supplied X-User-ID does not resolve to a %s row." % role,
            )
    return user_id, role


def mismatch():
    raise ApiError("ERR_RESOURCE_MISMATCH")


def own_facility(user_id, role, facility_id):
    """Priority 4 for a Borrower addressing a facility-scoped row."""
    if role == BORROWER and facility_id != user_id:
        mismatch()


def own_custodian(user_id, role, custodian_id):
    if role == CUSTODIAN and custodian_id != user_id:
        mismatch()


def own_investor(user_id, role, investor_id):
    if role == INVESTOR and investor_id != user_id:
        mismatch()
