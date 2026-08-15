"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2)."""
from flask import request

import store
from errors import ERR_AUTH, ERR_FORBIDDEN_ROLE, raise_err

ROLES = {
    "CorporateSecretary",
    "FilingCoordinator",
    "AuthorizedOfficer",
    "RegisteredAgentUser",
    "ComplianceAuditor",
}

ALL_ROLES = [
    "CorporateSecretary",
    "FilingCoordinator",
    "AuthorizedOfficer",
    "RegisteredAgentUser",
    "ComplianceAuditor",
]


def current_user():
    """Priority 1: headers present, role declared, entity-backed id resolves."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_AUTH, "Missing or invalid X-User-ID / X-User-Role headers")
    if role == "AuthorizedOfficer" and user_id not in store.officers:
        raise_err(ERR_AUTH, "X-User-ID must reference an existing Officer")
    if role == "RegisteredAgentUser" and user_id not in store.registered_agents:
        raise_err(ERR_AUTH, "X-User-ID must reference an existing RegisteredAgent")
    return user_id, role


def require_roles(allowed):
    """Priority 1 then priority 2 (role permitted for the endpoint)."""
    user_id, role = current_user()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


def get_body(required=True):
    """Parse a JSON request body; must be an object when present."""
    data = request.get_json(silent=True)
    if data is None:
        if required and request.data:
            raise_err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data
