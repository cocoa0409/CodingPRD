"""Auth context (PRD §2.1): X-User-ID + X-User-Role headers on every request.

Roles: Trustee, Clerk, Court, Creditor (exact spelling). Missing or malformed
headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); a role not
permitted for the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

from errors import ApiError, ERR_MISSING_CONTEXT, ERR_FORBIDDEN_FOR_ROLE

ROLES = ("Trustee", "Clerk", "Court", "Creditor")
ALL_ROLES = ROLES


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise ApiError(ERR_MISSING_CONTEXT, 400, "X-User-ID and X-User-Role headers are required.")
    if not isinstance(uid, str) or uid.strip() == "":
        raise ApiError(ERR_MISSING_CONTEXT, 400, "X-User-ID header is malformed.")
    if role not in ROLES:
        raise ApiError(ERR_MISSING_CONTEXT, 400, "X-User-Role header is malformed.")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, "Role is not permitted for this endpoint.")


def json_body():
    """Return the parsed JSON body as a dict; {} when absent; 400 on malformed."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return data
