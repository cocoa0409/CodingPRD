"""Auth header extraction & RBAC (PRD §2.1, §2.7).

Headers:
  X-User-ID   - acting principal id (opaque for AgencyAdmin/AccountManager,
                entity id for Reseller/Client)
  X-User-Role - one of AgencyAdmin | AccountManager | Reseller | Client

Validation order (per §2.7) is enforced by the calling routes via these helpers:
  1. auth presence/well-formedness (ERR_MISSING_AUTH)
  2. role permitted for endpoint (ERR_FORBIDDEN_ROLE)
  3. ownership for entity-backed actors (ERR_NOT_RESOURCE_OWNER)
"""
from flask import request

from errors import err

VALID_ROLES = {"AgencyAdmin", "AccountManager", "Reseller", "Client"}
ENTITY_BACKED = {"Reseller", "Client"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Validate auth headers and return a Principal, else raise ERR_MISSING_AUTH.

    X-User-Role must be present and a recognized role. X-User-ID must be present
    and non-empty (mandatory for all roles; explicitly mandatory for
    entity-backed roles).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH", "Missing or malformed X-User-Role header")
    if user_id is None or not str(user_id).strip():
        raise err("ERR_MISSING_AUTH", "Missing or malformed X-User-ID header")
    return Principal(str(user_id).strip(), role)


def require_role(principal, allowed_roles):
    """Ensure the acting role is permitted for this endpoint."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
