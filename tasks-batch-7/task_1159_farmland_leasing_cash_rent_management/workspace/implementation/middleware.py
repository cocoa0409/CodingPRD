"""Auth header extraction and role checking per PRD 2.1 and validations priority 1-2."""
from flask import request
from errors import ApiError

VALID_ROLES = {"FarmManager", "Landlord", "Tenant", "System"}


def get_caller():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-Role header missing or malformed")
    return user_id.strip(), role


def require_role(role, allowed):
    """Raises ERR_FORBIDDEN_FOR_ROLE (403) if role not in allowed."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                       f"Role {role} not authorized for this endpoint")


def get_json_body(required=True):
    """Return parsed JSON body as dict; {} if empty and not required.
    Raises ERR_VALIDATION on malformed JSON."""
    if request.content_length == 0 and not request.data:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Request body is required")
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Request body is not valid JSON")
    if body is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Request body is required")
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body
