"""Auth header extraction and role checking (PRD §2.1, validations 1-3)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"FoodBankOperator", "AllocationManager", "AgencyCoordinator", "ComplianceAuditor"}


def get_identity():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2)."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role is not permitted to perform this operation.")
