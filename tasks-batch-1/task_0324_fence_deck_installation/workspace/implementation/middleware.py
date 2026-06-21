"""Auth/RBAC middleware and request-body helpers (PRD §2.1, §2.9)."""
from flask import request

from errors import err

KNOWN_ROLES = {"ProjectManager", "Estimator", "FieldTech", "PermitClerk", "Customer"}


def auth_context():
    """Validate authentication (priority 1). Returns (role, user_id).

    A missing or unknown X-User-Role yields ERR_UNAUTHENTICATED (401).
    The X-User-ID is opaque for the four operator roles; for Customer it is
    the id of the acting Customer record (entity-backed identity).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED")
    return role, user_id


def require_role(role, allowed):
    """Authorization check (priority 2). ERR_FORBIDDEN (403) if not allowed."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN")


def body():
    """Return the JSON body as a dict, tolerating empty/missing bodies."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data
