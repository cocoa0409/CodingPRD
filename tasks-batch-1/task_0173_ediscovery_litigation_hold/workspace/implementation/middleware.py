"""Auth header extraction and RBAC (PRD §2.1)."""
from flask import request

import errors

KNOWN_ROLES = {"LegalOps", "ReviewLead", "Reviewer", "Producer", "Custodian"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
