"""Auth header extraction and RBAC checks (PRD §2.1, §1.7)."""
from flask import request

import errors

VALID_ROLES = {"Underwriter", "ClaimsExaminer", "CareAssessor", "Regulator", "Policyholder"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns a Caller.

    Missing or malformed (empty / unknown role) -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing authentication headers")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Malformed authentication headers")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unknown role")
    return Caller(user_id, role)


def authorize(caller, allowed_roles):
    """Authorization: acting role must be permitted for this operation."""
    if caller.role not in allowed_roles:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")
