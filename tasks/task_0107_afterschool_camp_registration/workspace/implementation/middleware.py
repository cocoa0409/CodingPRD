"""Auth middleware + RBAC helpers."""

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import APIError


def require_auth(allowed_roles):
    """Decorator that enforces validation priorities 1-3 (per SCAFFOLD §1.4):

      1. X-User-Role header present and in {ProgramAdmin, Guardian} else ERR_AUTH_REQUIRED
      2. X-User-ID header present and non-empty else ERR_AUTH_REQUIRED
      3. Role in allowed_roles for this endpoint else ERR_FORBIDDEN
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_role = request.headers.get(HEADER_USER_ROLE)
            user_id = request.headers.get(HEADER_USER_ID)
            if not user_role or user_role not in ROLES:
                raise APIError("ERR_AUTH_REQUIRED")
            if not user_id or not user_id.strip():
                raise APIError("ERR_AUTH_REQUIRED")
            if user_role not in allowed_roles:
                raise APIError("ERR_FORBIDDEN")
            g.user_id = user_id
            g.user_role = user_role
            return view(*args, **kwargs)
        return wrapped
    return decorator


def get_json_body():
    """Return request JSON body as dict, or {} if absent. Raise ERR_VALIDATION on malformed JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise APIError("ERR_VALIDATION", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body
