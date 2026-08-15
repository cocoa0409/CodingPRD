"""Auth context extraction and role checking (pipeline categories 1-3)."""
from flask import request

from errors import err_missing_context, err_forbidden_role, err_ownership

ROLES = {
    "Anonymous",
    "Handler",
    "Evaluator",
    "FacilityCoordinator",
    "ProgramAdmin",
    "ComplianceOfficer",
}

# Roles whose X-User-ID is an opaque operator identifier (never compared to entity ids)
OPAQUE_ROLES = {"ProgramAdmin", "ComplianceOfficer", "Anonymous"}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in ("Handler", "Evaluator", "FacilityCoordinator")


def get_auth():
    """Pipeline step 1: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_missing_context()
    return AuthContext(user_id, role)


def require_roles(auth, allowed):
    """Pipeline step 2: role authorization."""
    if auth.role not in allowed:
        raise err_forbidden_role()


def ownership_mismatch():
    raise err_ownership()
