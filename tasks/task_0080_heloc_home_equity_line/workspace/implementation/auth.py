"""Auth header extraction and RBAC enforcement."""
from flask import request

from errors import err

KNOWN_ROLES = {"LoanOfficer", "LoanServicer", "Borrower", "Auditor"}


def get_identity():
    """Validate X-User-ID / X-User-Role headers. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not permitted."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
