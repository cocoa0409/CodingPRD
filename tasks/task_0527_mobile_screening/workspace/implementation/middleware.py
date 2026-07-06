"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request
from errors import err

KNOWN_ROLES = {
    "ProgramManager",
    "ClinicalStaff",
    "BillingClerk",
    "PatientNavigator",
    "SponsorViewer",
}


def require_user_context():
    """Priority 1: X-User-ID and X-User-Role present, role known.
    Returns (user_id, role) or raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID / X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role must be in the allowed set for the operation."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s not permitted for this operation" % role)
