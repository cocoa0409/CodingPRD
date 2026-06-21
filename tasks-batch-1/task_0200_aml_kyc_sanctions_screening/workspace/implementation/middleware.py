"""Auth header extraction and RBAC (PRD §2.1, §1.7).

Every request must carry X-User-ID and X-User-Role. X-User-Role must be one of
the five recognized roles. All five roles use an OPAQUE identity model — X-User-ID
is never compared to any entity id for ownership purposes.
"""

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"ComplianceOfficer", "Analyst", "QualityReviewer", "SystemFeed", "PlatformAdmin"}


def authenticate():
    """Validate presence + known-role of the auth headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing header or
    unknown role. (priority 1)
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header.")
    if role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown X-User-Role.")
    return user_id, role


def require_role(role, allowed):
    """Authorization check (priority 2). Raises ERR_FORBIDDEN if role not allowed."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation.")
