"""Auth header extraction and RBAC (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. A missing/unrecognized
role -> ERR_UNAUTHENTICATED. A role not permitted for the operation, or an
ownership mismatch -> ERR_FORBIDDEN.
"""

from flask import request

from errors import err

ROLES = {"ProgramAdmin", "StoreAssociate", "Customer", "FraudAnalyst", "B2BBuyer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if the role header is
    missing or not one of the five recognized roles (PRD §2.1)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Authorization (priority 2). Raises ERR_FORBIDDEN if role not in allowed."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")
