"""Auth header extraction and role checking (priority 1 and 2 of the validation cascade)."""
from flask import request

from errors import err_unauthenticated, err_forbidden_role

ROLES = {
    "RegistrationPrincipal",
    "ComplianceOfficer",
    "FinanceClerk",
    "SystemOperator",
    "Regulator",
}


def auth(*allowed_roles):
    """Validate X-User-ID / X-User-Role; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    if role not in set(allowed_roles):
        raise err_forbidden_role()
    return uid, role
