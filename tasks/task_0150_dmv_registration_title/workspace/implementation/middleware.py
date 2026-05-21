"""Request-level middleware: auth header validation, RBAC, JSON body parsing.

Validation priority (SCAFFOLD §1.4 / PRD §2.8):
  1. Header presence (X-User-ID and X-User-Role) -> ERR_AUTH_REQUIRED (401)
  2. Role recognition (must be one of nine declared roles) -> ERR_INVALID_ROLE (403)
  3. Role permission for the operation -> ERR_ROLE_FORBIDDEN (403)
"""

from functools import wraps
from flask import request, g

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import make_error


def parse_json_body() -> dict:
    """Parse the incoming JSON body. Returns {} for missing/empty body.

    Body MUST be a JSON object (not array/scalar). Malformed JSON raises
    ERR_VALIDATION; a non-object body raises ERR_VALIDATION as well.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        raw = request.get_data(cache=True)
        if not raw:
            return {}
        try:
            body = request.get_json(force=True, silent=False, cache=True)
        except Exception:
            raise make_error("ERR_VALIDATION", "Malformed JSON body.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise make_error("ERR_VALIDATION", "Request body must be a JSON object.")
        return body
    return {}


def require_auth(*, allowed_roles: list[str] | None = None):
    """Decorator: enforce auth (presence + role enum) and RBAC for an endpoint.

    Priority order (SCAFFOLD §1.4):
      1. Missing X-User-ID OR missing X-User-Role -> ERR_AUTH_REQUIRED (401)
      2. X-User-Role not in the role enum -> ERR_INVALID_ROLE (403)
      3. X-User-Role not in allowed_roles for this endpoint -> ERR_ROLE_FORBIDDEN (403)
    """
    allowed_set = set(allowed_roles or [])

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get(HEADER_USER_ID)
            role = request.headers.get(HEADER_USER_ROLE)
            # Priority 1: header presence (both required)
            if not user_id or not role:
                raise make_error("ERR_AUTH_REQUIRED")
            # Priority 2: role enum
            if role not in ROLES:
                raise make_error("ERR_INVALID_ROLE")
            # Priority 3: role permission for this endpoint
            if allowed_set and role not in allowed_set:
                raise make_error("ERR_ROLE_FORBIDDEN")
            # Expose identity for downstream ownership/segregation checks.
            g.user_role = role
            g.user_id = user_id
            return view(*args, **kwargs)

        return wrapped

    return decorator
