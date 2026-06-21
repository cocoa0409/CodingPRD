"""Auth header extraction and role checking.

PRD §2.1: every request must carry X-User-ID and X-User-Role. Recognized roles
are exactly: PlatformAdmin, PayrollOfficer, ComplianceOfficer, Worker. A missing
header or unknown role -> ERR_UNAUTHENTICATED (401). A valid role not permitted
for the operation -> ERR_UNAUTHORIZED (403).
"""
from flask import request

import errors

ROLES = {"PlatformAdmin", "PayrollOfficer", "ComplianceOfficer", "Worker"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Validation priority 1 (PRD §2.11): both headers present and the role is a
    known role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (PRD §2.11): role must be in the allowed set."""
    if role not in allowed:
        raise errors.unauthorized()
