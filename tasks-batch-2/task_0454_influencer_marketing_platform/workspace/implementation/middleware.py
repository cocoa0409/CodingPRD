"""Auth header extraction and role checking (PRD 2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"Brand", "Creator", "ComplianceOfficer", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if missing/malformed.

    Every request must carry X-User-ID and X-User-Role; if either header is
    missing or malformed, reject with ERR_UNAUTHENTICATED (401) before any other
    processing (PRD 2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Reject with ERR_FORBIDDEN_ROLE if role not in allowed (PRD 2.1)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)
