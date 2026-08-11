"""Auth header extraction and role checking (SCAFFOLD §1.4 priority 1-2, §1.7)."""

from flask import request

import errors

ROLES = {
    "HousingDeveloper",
    "MarketingCoordinator",
    "ApplicationClerk",
    "ComplianceOfficer",
    "LotteryAdministrator",
    "FundingAgencyAuditor",
    "Applicant",
    "Anonymous",
}

STAFF_ROLES = {
    "HousingDeveloper",
    "MarketingCoordinator",
    "ApplicationClerk",
    "ComplianceOfficer",
    "LotteryAdministrator",
    "FundingAgencyAuditor",
}


class Caller:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def authenticate() -> Caller:
    """Priority 1: X-User-Role present and declared; X-User-ID required for non-Anonymous."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "missing or unrecognized X-User-Role")
    if role != "Anonymous" and not user_id:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "missing X-User-ID")
    return Caller(role, user_id)


def require_roles(caller: Caller, allowed):
    """Priority 2 endpoint-level role list."""
    if caller.role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "role not permitted on this endpoint")


def require_action_role(caller: Caller, action: str, mapping: dict):
    """Action-level role mapping; mapping[action] is the set of roles allowed."""
    allowed = mapping.get(action)
    if allowed is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "unknown action")
    if caller.role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE, "action-level role violation")
