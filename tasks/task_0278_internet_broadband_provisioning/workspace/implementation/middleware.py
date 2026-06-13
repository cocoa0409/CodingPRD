"""Auth header extraction and role checking (PRD §2.1, §3.12 validation order).

Validation priority (PRD §3.12 / scaffold Table 4):
  1. auth headers present/well-formed -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
  2. role permitted for endpoint     -> ERR_FORBIDDEN_FOR_ROLE
  ... (existence, body, state, ownership, business checks handled per-route)
"""
from flask import request

from errors import err

VALID_ROLES = {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"}


def get_user_context():
    """Extract and validate the X-User-ID / X-User-Role headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required.")
    if not isinstance(user_id, str) or user_id.strip() == "":
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID header is malformed.")
    if role not in VALID_ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role header is missing or not a recognized role.")
    return user_id, role


def require_role(role, allowed):
    """Authorization check (priority 2)."""
    if role not in allowed:
        err("ERR_FORBIDDEN_FOR_ROLE",
            "Role %s is not permitted to invoke this operation." % role)
