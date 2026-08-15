"""Authentication / RBAC middleware.

Every request carries X-User-ID and X-User-Role. Missing/empty headers or an
undeclared role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). A
well-formed role not authorized for the endpoint -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err

ROLES = {"PlatformAdmin", "RecordsManager", "LegalCounsel", "Auditor", "Custodian"}

ALL_ROLES = ["PlatformAdmin", "RecordsManager", "LegalCounsel", "Auditor", "Custodian"]
READ_STAFF = ["PlatformAdmin", "RecordsManager", "LegalCounsel", "Auditor"]


def authenticate(allowed_roles):
    """Validate headers, then role authorization. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "" or role is None or role.strip() == "" \
            or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                  "X-User-ID and X-User-Role headers must both be present, "
                  "non-empty, and name a declared role")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", 403,
                  "Role %s is not authorized for this endpoint" % role)
    return uid, role


def body_json():
    """Parse the JSON request body; an absent or unparsable body is {}."""
    data = request.get_json(silent=True, force=False)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data
