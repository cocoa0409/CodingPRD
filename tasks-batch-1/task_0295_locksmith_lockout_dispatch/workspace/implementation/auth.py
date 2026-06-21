"""Auth header extraction and RBAC enforcement (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"Dispatcher", "Technician", "Customer", "InventoryManager", "BillingAgent"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_principal():
    """Validate X-User-ID and X-User-Role presence/well-formedness.

    Raises ERR_MISSING_AUTH_CONTEXT (401) when either header is absent,
    blank, or carries an unrecognized role value.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_AUTH_CONTEXT", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_AUTH_CONTEXT", "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH_CONTEXT", "Malformed or unknown X-User-Role header")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Authorization (ERR_FORBIDDEN_ROLE, 403) when role not permitted."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % principal.role)
