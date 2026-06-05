"""Auth + RBAC (PRD §2.1, §2.10, scaffold §1.7).

Every request carries two mandatory headers:
  - X-User-ID   : opaque acting-operator id
  - X-User-Role : one of exactly {Owner, Contractor, Architect}

Priority order (PRD §2.10): auth (401) -> role (403) -> existence (404) -> ...
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"Owner", "Contractor", "Architect"}


def authenticate():
    """Validate presence of headers and that the role is known. Returns
    (user_id, role) or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-ID / X-User-Role.")
    return user_id, role


def require_role(role, allowed):
    """allowed is a set/list of role names permitted for the endpoint."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role '%s' may not invoke this operation." % role)
