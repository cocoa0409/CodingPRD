"""Auth header extraction and role checking (§2.1, §2.10)."""
from flask import request

import errors

VALID_ROLES = {"ServicerOps", "ComplianceOfficer", "Borrower", "HudAuditor", "System"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).
    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400) if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                         "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                         "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                         "Unrecognized X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_FOR_ROLE (403) if role not in the allowed set."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE,
                         "Role %s not permitted for this operation" % role)
