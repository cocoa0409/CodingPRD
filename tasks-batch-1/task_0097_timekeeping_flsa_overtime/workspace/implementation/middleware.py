"""Auth header extraction and role checking (PRD §2.1, §2.8)."""
from flask import g, request

from errors import err

KNOWN_ROLES = {"PayrollAdmin", "Supervisor", "Employee"}


def authenticate():
    """Validate X-User-Role (and X-User-ID for Employee).

    Priority 1 (validations §1.4): X-User-Role present and a known role, else
    ERR_UNAUTHENTICATED. Priority 2: X-User-ID present for the Employee role
    (entity-backed identity), else ERR_UNAUTHENTICATED.

    Stores the acting identity on flask.g.
    """
    role = request.headers.get("X-User-Role")
    if not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header missing or unknown.")

    user_id = request.headers.get("X-User-ID")
    # Employee acts in their own name: X-User-ID is the acting Employee.id and
    # is required (PRD §2.1).
    if role == "Employee" and not user_id:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID header is required for Employee.")

    g.user_role = role
    g.user_id = user_id


def require_role(*allowed_roles):
    """Priority 3: the acting role must be permitted for the operation, else
    ERR_FORBIDDEN (PRD §2.8 / §1.7 RBAC matrix)."""
    if g.user_role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")
