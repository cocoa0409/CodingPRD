"""Request-level middleware: auth header validation, RBAC, JSON body parsing.

Validation priority (SCAFFOLD §1.4 / PRD §2.11):
  1. Header presence (X-User-ID and X-User-Role) -> ERR_UNAUTHENTICATED (401)
  2. Role enum (must be one of Applicant, Examiner, USPTOAdmin) -> ERR_FORBIDDEN (403)
  3. Role permission for the operation -> ERR_FORBIDDEN (403)
"""

from functools import wraps
from flask import request, g

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import make_error


def parse_json_body(required_fields: list[str] | None = None) -> dict:
    """Parse the incoming JSON body. Returns {} for missing/empty body."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not request.data:
            body = {}
        else:
            try:
                body = request.get_json(force=True, silent=False)
            except Exception:
                raise make_error("ERR_BAD_REQUEST", "Malformed JSON body.")
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise make_error("ERR_BAD_REQUEST", "Request body must be a JSON object.")
        if required_fields:
            for field in required_fields:
                if field not in body or body[field] is None:
                    raise make_error("ERR_BAD_REQUEST", f"Missing required field: {field}")
        return body
    return {}


def require_auth(*, allowed_roles: list[str] | None = None, public: bool = False):
    """Decorator: enforce auth (presence + role enum) and RBAC for an endpoint.

    Priority order:
      1. Missing X-User-ID OR missing X-User-Role -> ERR_UNAUTHENTICATED (401)
      2. X-User-Role not in the role enum -> ERR_FORBIDDEN (403)
      3. X-User-Role not in allowed_roles for this endpoint -> ERR_FORBIDDEN (403)

    `public=True` skips all auth (only used for nothing currently — every
    endpoint requires at least header presence).
    """
    allowed_set = set(allowed_roles or [])

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if public:
                return view(*args, **kwargs)
            role = request.headers.get(HEADER_USER_ROLE)
            user_id = request.headers.get(HEADER_USER_ID)
            # Priority 1: presence
            if not user_id or not role:
                raise make_error("ERR_UNAUTHENTICATED")
            # Priority 2: role enum
            if role not in ROLES:
                raise make_error("ERR_FORBIDDEN")
            # Priority 3: role permission for this endpoint
            if allowed_set and role not in allowed_set:
                raise make_error("ERR_FORBIDDEN")
            # Expose identity on flask.g for ownership checks downstream.
            g.user_role = role
            g.user_id = user_id
            return view(*args, **kwargs)

        return wrapped

    return decorator
