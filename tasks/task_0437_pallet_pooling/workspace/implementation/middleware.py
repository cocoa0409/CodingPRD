"""Auth header extraction, RBAC and request-body helpers.

PRD §2.1: every request must carry X-User-ID and X-User-Role. Roles are exactly
PoolAdmin, PoolOperator, Participant. Missing/malformed -> ERR_MISSING_AUTH (401);
role not permitted for the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"PoolAdmin", "PoolOperator", "Participant"}


def get_auth():
    """Validate auth headers (validation priority 1, PRD §2.10).

    Returns (user_id, role). Raises ERR_MISSING_AUTH on missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_AUTH", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_AUTH", "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH", "Malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (validation priority 2, PRD §2.10).

    PoolAdmin capability set is a superset of PoolOperator (PRD §2.1): wherever
    PoolOperator is allowed, PoolAdmin is also allowed. We honor that by
    expanding the allowed set, but the endpoint tables already list PoolAdmin
    explicitly everywhere PoolOperator appears, so the membership test suffices.
    """
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this operation" % role)


def get_json_body():
    """Return the JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object is malformed (ERR_INVALID_REQUEST).
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body
