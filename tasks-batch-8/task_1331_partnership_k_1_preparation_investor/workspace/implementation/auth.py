"""Authentication and role authorization."""
from flask import request

from util import ApiError

ROLES = {"FundTaxAdmin", "TaxPreparer", "TaxReviewer", "InvestorServicesRep", "Investor"}

ALL_ROLES = ("FundTaxAdmin", "TaxPreparer", "TaxReviewer", "InvestorServicesRep", "Investor")
ADMIN_ROLES = ("FundTaxAdmin", "TaxPreparer", "TaxReviewer", "InvestorServicesRep")
TRIO_ROLES = ("FundTaxAdmin", "TaxPreparer", "TaxReviewer")


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_CONTEXT", 400, "Missing or unknown X-User-ID / X-User-Role header")
    return uid, role


def require_roles(*roles):
    uid, role = auth_context()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for this endpoint")
    return uid, role
