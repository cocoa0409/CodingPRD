"""Auth context extraction and role checks (PRD 2.1, validation priorities 1-2)."""

from flask import request

from errors import fail

ROLES = {
    "CollegeAdmin",
    "WorkforceCoordinator",
    "CredentialOfficer",
    "GrantOfficer",
    "EmployerContact",
    "BillingClerk",
    "Instructor",
}

ALL_ROLES = sorted(ROLES)


def auth_context():
    """Priority 1: X-User-ID and X-User-Role must be present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID header is missing or malformed",
        )
    if role is None or role not in ROLES:
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role header is missing or malformed",
        )
    return uid.strip(), role


def require_roles(*roles):
    """Priority 1 then priority 2 (role authorization). Returns (user_id, role)."""
    uid, role = auth_context()
    if role not in roles:
        fail("ERR_FORBIDDEN_FOR_ROLE", f"Role {role} is not authorized for this endpoint")
    return uid, role


def check_employer_scope(uid, role, employer_id):
    """Entity-backed ownership for EmployerContact reads/actions (PRD 2.1)."""
    if role == "EmployerContact" and uid != employer_id:
        fail("ERR_FORBIDDEN_FOR_ROLE", "EmployerContact may only access its own employer scope")
