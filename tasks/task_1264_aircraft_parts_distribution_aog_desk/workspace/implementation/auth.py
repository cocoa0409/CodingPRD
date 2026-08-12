"""Authentication / authorization per PRD section 2.1."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "AogDeskAgent",
    "CustomerContact",
    "WarehouseOperator",
    "ComplianceOfficer",
    "FinanceController",
    "WarrantyAdjuster",
    "WarrantyApprover",
    "PlatformOps",
}

ALL_BUSINESS = [
    "AogDeskAgent", "CustomerContact", "WarehouseOperator", "ComplianceOfficer",
    "FinanceController", "WarrantyAdjuster", "WarrantyApprover",
]

LEDGER_READERS = [
    "AogDeskAgent", "WarehouseOperator", "ComplianceOfficer",
    "FinanceController", "WarrantyAdjuster", "WarrantyApprover",
]


def authenticate():
    """Priority 1: headers present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def require_roles(*roles):
    """Priority 1 + 2: authentication, then role permitted for the endpoint."""
    uid, role = authenticate()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return uid, role


def forbid_unless_owner(role, uid, customer_id):
    """CustomerContact callers may only act on their own resources."""
    if role == "CustomerContact" and customer_id != uid:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "CustomerContact may only act on own resources")
