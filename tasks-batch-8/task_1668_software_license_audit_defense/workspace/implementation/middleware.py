"""Auth header extraction and role checking (PRD §2.1).

All endpoints require X-User-ID and X-User-Role. X-User-ID is an opaque
operator identifier; X-User-Role must name one of the six declared roles.
"""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLE_PLATFORM_ADMIN = "SAMPlatformAdmin"
ROLE_SAM_MANAGER = "SAMManager"
ROLE_IT_ANALYST = "ITAnalyst"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_PROCUREMENT_LEAD = "ProcurementLead"
ROLE_VENDOR_AUDITOR = "VendorAuditor"

ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_SAM_MANAGER,
    ROLE_IT_ANALYST,
    ROLE_LEGAL_COUNSEL,
    ROLE_PROCUREMENT_LEAD,
    ROLE_VENDOR_AUDITOR,
}

ALL_ROLES = sorted(ROLES)

# The five internal roles: everything except the external VendorAuditor.
INTERNAL_ROLES = [r for r in ALL_ROLES if r != ROLE_VENDOR_AUDITOR]


def actor():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(allowed):
    """Return (user_id, role) if the role is authorized for this endpoint."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Role is not permitted for this endpoint")
    return user_id, role
