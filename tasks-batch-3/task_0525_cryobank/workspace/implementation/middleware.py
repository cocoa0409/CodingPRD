from flask import request

import errors
from errors import err

ROLES = {
    "ScreeningOfficer",
    "LabTech",
    "ComplianceOfficer",
    "CatalogManager",
    "Recipient",
    "BillingClerk",
}


def get_auth():
    """Validate auth headers. Returns (user_id, role) or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
