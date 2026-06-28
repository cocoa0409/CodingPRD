"""Auth header extraction and RBAC per PRD 2.1.

Two mandatory headers: X-User-ID and X-User-Role. A request missing either
header, or carrying a header the server cannot interpret (an unrecognized role),
is rejected with ERR_UNAUTHENTICATED. When headers are present and valid but the
declared role is not permitted, the request is rejected with ERR_FORBIDDEN.
"""
from flask import request

import errors

VALID_ROLES = {"StudioAdmin", "FrontDesk", "Technician", "ComplianceOfficer"}


def authenticate():
    """Validate the two auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unrecognized X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Role authorization. ERR_FORBIDDEN when role not in allowed set."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
