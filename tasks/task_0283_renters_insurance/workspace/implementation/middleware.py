"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 / §1.7).

Every request carries two mandatory headers:
  X-User-ID   — acting user id
  X-User-Role — one of exactly Underwriter | Policyholder | ClaimsAdjuster
Missing/malformed -> ERR_UNAUTHENTICATED (401).
Role not permitted for the operation -> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"Underwriter", "Policyholder", "ClaimsAdjuster"}


def authenticate():
    """Validate the auth headers. Returns (user_id, role). Raises on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed_roles):
    """Enforce that `role` is in `allowed_roles`, else ERR_FORBIDDEN."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role {} not permitted for this operation".format(role))
