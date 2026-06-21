"""Authentication / authorization (PRD §2.1, §2.11).

Headers (verbatim from PRD §2.1):
  X-User-ID    — acting principal id
  X-User-Role  — one of {Admin, Underwriter, PolicyOwner}

Binding:
  Admin        — X-User-ID is opaque (not required, not tied to any entity).
  Underwriter  — X-User-ID is the acting Underwriter.id (required).
  PolicyOwner  — X-User-ID is the acting Applicant.id (required).
"""
from flask import request

from errors import err

ROLES = {"Admin", "Underwriter", "PolicyOwner"}
# Roles whose identity header is mandatory (entity-backed).
ENTITY_BACKED = {"Underwriter", "PolicyOwner"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers; raise ERR_UNAUTHENTICATED on failure.

    Priority 1 in the validation order. Runs before everything else.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header.")

    if role in ENTITY_BACKED and (user_id is None or user_id == ""):
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID header for an entity-backed role.")

    return Principal(user_id, role)


def authorize(principal, allowed_roles):
    """Priority 2: role must be permitted for this endpoint."""
    if principal.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation.")
