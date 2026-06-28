"""Auth header extraction and RBAC helpers (PRD §2.1, §2.9)."""
from flask import request

from errors import err

ROLES = {"Parent", "Child", "PlatformAdmin"}


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1 (PRD §2.9): both headers present and the role recognized,
    else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized auth headers")
    return Identity(user_id, role)


def require_role(identity, allowed_roles):
    """Priority 2: the acting role must be permitted for this operation."""
    if identity.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def get_json_body():
    """Parse the JSON body. Missing body is treated as an empty object so that
    no-input POSTs (e.g. suspend, approve) work without a body. A present but
    malformed JSON body is rejected with ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body
