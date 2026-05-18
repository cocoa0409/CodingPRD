"""Request-level middleware: auth header validation and JSON body parsing.

PRD §2.1 / SCAFFOLD validations priority 1-2:
  - Every request must carry X-User-ID and X-User-Role (Role is the gate).
  - X-User-Role must be one of {Debtor, Trustee, Creditor, Judge} else ERR_UNAUTHENTICATED (401).
  - Per-endpoint RBAC denial yields ERR_FORBIDDEN (403).
"""

from functools import wraps
from flask import request, g

from config import ROLES
from errors import make_error


def parse_json_body(required_fields: list[str] | None = None) -> dict:
    """Parse the incoming JSON body and validate required fields.

    Raises ERR_BAD_REQUEST (400) for missing / malformed body or fields.
    """
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


def require_auth(*, allowed_roles: list[str]):
    """Decorator: enforce auth (presence + role enum) and RBAC for an endpoint.

    The role check uses the scaffold's exact role names. A missing role or one
    outside the four-role enum yields ERR_UNAUTHENTICATED. A well-formed role
    that isn't in allowed_roles for this endpoint yields ERR_FORBIDDEN.
    """
    allowed_set = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if role is None or role not in ROLES:
                raise make_error("ERR_UNAUTHENTICATED")
            if role not in allowed_set:
                raise make_error("ERR_FORBIDDEN")
            # User-ID may be absent for opaque-identity roles; we still expose
            # whatever was sent on flask.g for ownership checks downstream.
            g.user_role = role
            g.user_id = user_id
            return view(*args, **kwargs)

        return wrapped

    return decorator
