"""Auth header extraction and RBAC (PRD §2.1, §1.7)."""
from flask import request

from errors import err

ROLES = {"Customer", "SalesRep", "Scheduler", "InstallCrew", "PlatformAdmin"}


def require_auth():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    PRD §2.1: both headers mandatory; unknown role => ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE when the role is not in the allowed set.

    PlatformAdmin is the operator superset and may perform any operation
    (PRD §2.1, §1.7); it is therefore always permitted.
    """
    if role == "PlatformAdmin":
        return
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
