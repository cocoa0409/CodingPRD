"""Auth middleware: X-User-ID / X-User-Role extraction and role enforcement."""
from flask import request

from errors import err

ROLES = {
    "ServicingAdmin",
    "PropertySolutionsSpecialist",
    "WorkoutManager",
    "TitleOfficer",
    "Borrower",
    "Inspector",
    "DisbursementOfficer",
    "LegalCounsel",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role).

    Priority 1: headers present and role declared -> ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed: str):
    """Authenticate then check endpoint role authorization (priority 2)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err("ERR_FORBIDDEN",
                  f"Role {role} is not permitted on this endpoint")
    return user_id, role
