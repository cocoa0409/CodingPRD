"""Auth header extraction and role checking (PRD §2.1, §2.10).

Headers (verbatim PRD §2.1):
  X-User-ID   — identifies the acting user (opaque for all four roles)
  X-User-Role — operational capacity; one of Registrar, Guide,
                ComplianceOfficer, Parent
"""
from flask import request

import errors

KNOWN_ROLES = {"Registrar", "Guide", "ComplianceOfficer", "Parent"}


def get_auth():
    """Validate presence of both headers and a known role.

    Raises ERR_UNAUTHENTICATED (401) when either header is missing or the
    role is not recognized. Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) if the acting role is not permitted."""
    if role not in allowed:
        raise errors.forbidden_role()
