"""Auth middleware per PRD 2.1: X-User-ID + X-User-Role headers."""
from flask import request

from errors import err

ROLES = (
    "TerminalManager",
    "TerminalOperator",
    "Scheduler",
    "Gauger",
    "QualityInspector",
    "BillingClerk",
    "CustomerRep",
)


def current_user():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or unknown X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers, then endpoint role authorization."""
    user_id, role = current_user()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE",
                  "Role %s not permitted for this endpoint" % role)
    return user_id, role
