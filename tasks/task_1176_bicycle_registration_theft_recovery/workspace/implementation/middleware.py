"""Auth middleware (PRD §2.1, §2.6 stages 1-2) and request body helpers."""
import functools

from flask import g, request

from errors import fail

ROLES = {"Anonymous", "Owner", "Partner", "Registrar", "Admin"}


def require_roles(*roles):
    """Decorator: validates X-User-ID / X-User-Role headers (401), then that the
    acting role is in the endpoint's declared role list (403)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not isinstance(user_id, str) or not user_id.strip():
                fail("ERR_UNAUTHENTICATED", "X-User-ID header missing or malformed")
            if not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED", "X-User-Role header missing, malformed, or unknown")
            g.user_id = user_id
            g.role = role
            if role not in roles:
                fail("ERR_UNAUTHORIZED_ROLE", f"Role {role} is not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def body():
    """Request JSON body; malformed JSON or non-object bodies are 400s."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data
