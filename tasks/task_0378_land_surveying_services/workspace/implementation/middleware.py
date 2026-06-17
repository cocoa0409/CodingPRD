"""Auth header extraction and role checking (PRD §2.1, §2.9)."""
from flask import request

import errors

VALID_ROLES = {"Coordinator", "Researcher", "FieldTech", "Drafter", "Surveyor", "BillingClerk"}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and well-formed.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role headers")
    if not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: acting role permitted for this endpoint."""
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
