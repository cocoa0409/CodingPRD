"""Auth header extraction and RBAC enforcement.

Headers (PRD §2.1): X-User-ID and X-User-Role. Auth is decided purely by whether
the role appears in the operation's authorized set; X-User-ID is opaque and is
never matched against any entity (PRD §2.1).

Roles (exact spelling, PRD §2.1): AdmissionsOfficer, ServicingOfficer,
ComplianceOfficer, Student.
"""
from flask import request

import errors

ROLES = {"AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer", "Student"}


def require_role(*allowed):
    """Validate auth header presence/recognition, then RBAC.

    Priority order (PRD §2.8): ERR_UNAUTHENTICATED (401) before ERR_FORBIDDEN (403).
    Returns the recognized role string.
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise errors.unauthenticated()
    if allowed and role not in allowed:
        raise errors.forbidden()
    return role
