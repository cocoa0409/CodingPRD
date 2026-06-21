"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.12).

Every request carries X-User-ID and X-User-Role. The four roles are
CateringAdmin, Client, SalesCoordinator, EventCaptain. Auth is checked first
(ERR_UNAUTHENTICATED 401), then role authorization (ERR_FORBIDDEN_ROLE 403),
then — for Client-acted order/change-request operations — ownership
(ERR_NOT_RESOURCE_OWNER 403).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"CateringAdmin", "Client", "SalesCoordinator", "EventCaptain"}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_UNAUTHENTICATED, "missing or malformed X-User-ID")
    if not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or malformed X-User-Role")
    return user_id, role


def authorize(role, allowed_roles):
    """Role-to-endpoint matrix check (PRD §3.12, priority 2)."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "role %s may not invoke this endpoint" % role)
