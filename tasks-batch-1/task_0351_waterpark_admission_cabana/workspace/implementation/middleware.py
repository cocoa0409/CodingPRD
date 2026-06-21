"""Auth header extraction and role checking.

Header names and role values are read verbatim from PRD §2.1:
  X-User-ID, X-User-Role; roles Guest, GateAgent, ParkManager, FinanceClerk.
"""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"Guest", "GateAgent", "ParkManager", "FinanceClerk"}


def authenticate():
    """Validation priority 1 (PRD §2.9): both headers present and well-formed.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (PRD §2.9): acting role permitted for this op."""
    if role not in allowed:
        raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")
