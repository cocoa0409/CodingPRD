"""Auth header extraction and role checking (PRD §2.1).

Headers: X-User-ID and X-User-Role. Four roles, spelled precisely:
  FundManager, FundAdministrator, LimitedPartnerUser, ComplianceOfficer.

For FundManager / FundAdministrator / ComplianceOfficer, X-User-ID is opaque.
For LimitedPartnerUser, X-User-ID is the id of the acting LimitedPartner.
"""
from flask import request

import errors

VALID_ROLES = {
    "FundManager",
    "FundAdministrator",
    "LimitedPartnerUser",
    "ComplianceOfficer",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate presence/well-formedness of auth headers (priority 1).

    If either header is missing or malformed -> ERR_UNAUTHENTICATED (401),
    before any other processing.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        errors.fail(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header.")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """Role permission check (priority 2). -> ERR_FORBIDDEN_ROLE (403)."""
    if caller.role not in allowed_roles:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
