"""Auth header extraction and RBAC enforcement."""
from flask import request

from errors import err
from helpers import ROLES

SCOPED_ROLES = {"IntakeProcessor", "CaseInvestigator", "ContactTracer"}
UNSCOPED_ROLES = {"JurisdictionAdmin", "EpiAnalyst"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers required; role must be recognized")
    return user_id, role


def require_role(role, allowed):
    """RBAC role check (validation priority 2)."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s not permitted for this operation" % role)
