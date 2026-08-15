"""Auth header extraction and role checking per PRD section 2.1 / 2.8."""
from flask import request

import errors

ROLES = {"LicensingAnalyst", "Licensee", "LegalCounsel", "FinanceOfficer", "IPAdmin"}


def require_auth():
    """Validate X-User-Role and X-User-ID headers. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not user_id:
        raise errors.err_unauthenticated()
    return user_id, role


def require_role(*allowed):
    """Validate auth, then check the role is in the allowed set."""
    user_id, role = require_auth()
    if role not in allowed:
        raise errors.err_forbidden_role()
    return user_id, role
