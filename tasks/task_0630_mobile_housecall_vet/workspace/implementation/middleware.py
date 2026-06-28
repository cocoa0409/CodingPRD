"""Auth header extraction and RBAC (PRD §2.1, §2.6)."""
from flask import request

from errors import err

ROLES = {"Dispatcher", "Clinician", "ComplianceOfficer"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Missing or malformed -> ERR_MISSING_AUTH (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_AUTH", "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise err("ERR_MISSING_AUTH", "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Authorization gate. role not in allowed -> ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} not permitted for this operation")
