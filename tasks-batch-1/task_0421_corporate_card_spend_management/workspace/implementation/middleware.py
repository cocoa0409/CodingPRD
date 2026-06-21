"""Auth header extraction, role checking, request parsing helpers.

PRD §2.1: every request carries X-User-ID and X-User-Role.
Roles spelled exactly: FinanceAdmin, Approver, CardholderEmployee, Auditor.
"""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"FinanceAdmin", "Approver", "CardholderEmployee", "Auditor"}


def get_user_context():
    """Return (user_id, role). Raise ERR_MISSING_USER_CONTEXT if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "Missing or malformed X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Validate that role is in the allowed set, else ERR_FORBIDDEN_FOR_ROLE."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE,
                         "Role %s is not permitted for this operation." % role)


def get_json_body():
    """Parse JSON body; tolerate empty body (returns {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_VALIDATION, "Request body must be a JSON object.")
    return data
