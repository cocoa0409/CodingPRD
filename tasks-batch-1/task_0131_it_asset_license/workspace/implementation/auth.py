"""Authentication and RBAC (PRD 2.1, 2.8; scaffold 1.4 priorities 1-2, 1.7).

Headers (PRD 2.1):
  X-User-ID   — acting user identity (opaque for AssetManager/ComplianceOfficer;
                the Employee.id when role == Employee)
  X-User-Role — one of {AssetManager, ComplianceOfficer, Employee}
"""
from flask import request

from errors import err

VALID_ROLES = {"AssetManager", "ComplianceOfficer", "Employee"}


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the auth headers (priority 1).

    A request that omits either header, or whose X-User-Role is not one of the
    three recognised roles, is rejected with ERR_UNAUTHENTICATED (PRD 2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Authorize the operation (priority 2): role must be permitted (PRD 2.1/2.8)."""
    if caller.role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % caller.role)
