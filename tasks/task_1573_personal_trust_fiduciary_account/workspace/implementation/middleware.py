"""Auth header extraction and role checking (PRD section 2.1)."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "TrustOfficer",
    "TrustExecutive",
    "InvestmentManager",
    "TrustOperationsOfficer",
    "TaxSpecialist",
    "CommitteeMember",
    "Beneficiary",
}


def authenticate():
    """Priority 1: headers present and role declared. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or invalid X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    """Priority 3: role authorized for this endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s is not authorized for this operation" % role)
