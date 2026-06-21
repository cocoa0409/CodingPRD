"""Auth header extraction and RBAC checks (PRD 2.1, 2.10; scaffold 1.4)."""
from flask import request

from errors import ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED, err

# The five request-time role names (PRD 2.1).
ROLE_QUALITY_ENGINEER = "QualityEngineer"
ROLE_QUALITY_MANAGER = "QualityManager"
ROLE_INSPECTOR = "Inspector"
ROLE_AUDITOR = "Auditor"
ROLE_SUPPLIER_USER = "SupplierUser"

KNOWN_ROLES = {
    ROLE_QUALITY_ENGINEER,
    ROLE_QUALITY_MANAGER,
    ROLE_INSPECTOR,
    ROLE_AUDITOR,
    ROLE_SUPPLIER_USER,
}


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID and X-User-Role presence; role must be recognized.

    Returns an Auth. X-User-ID need not resolve to a persisted entity here;
    entity resolution is enforced only by ownership/SoD checks (PRD 2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return Auth(user_id, role)


def require_role(auth, allowed_roles):
    """Authorize the endpoint: the acting role must be permitted (PRD 2.1)."""
    if auth.role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % auth.role)
