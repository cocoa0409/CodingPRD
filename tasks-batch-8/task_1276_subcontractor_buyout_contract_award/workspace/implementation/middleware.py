"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = [
    "GCAdmin",
    "BuyoutLead",
    "OperationsManager",
    "ProjectExecutive",
    "ProjectManager",
    "VicePresident",
    "Estimator",
    "SupplierDiversity",
]

# Read roles shared by every declared role.
ALL_ROLES = list(ROLES)
# GET endpoints on negotiation rounds / certificates / bond decisions.
STANDARD_READ_ROLES = [
    "GCAdmin",
    "BuyoutLead",
    "OperationsManager",
    "ProjectExecutive",
    "ProjectManager",
    "VicePresident",
]
# Computed reads: buyout summary and replacement analysis.
SUMMARY_ROLES = ["GCAdmin", "OperationsManager", "VicePresident", "BuyoutLead"]
# Change-order read roles.
CO_READ_ROLES = STANDARD_READ_ROLES + ["SupplierDiversity"]


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
