"""Authentication, role authorization and entity-backed ownership (PRD 2.1)."""
from flask import g, request

from constants import ROLES
from errors import fail


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unrecognized.")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def user_id():
    return getattr(g, "user_id", None)


def role():
    return getattr(g, "role", None)


def is_shipper():
    return role() == "Shipper"


def is_terminal_operator():
    return role() == "TerminalOperator"


def require_owner(expected_id):
    if expected_id != user_id():
        fail("ERR_NOT_RESOURCE_OWNER", "Acting principal does not own the addressed resource.")


def require_shipper_owner(customer_id):
    """Ownership is only enforced for the entity-backed Shipper role."""
    if is_shipper():
        require_owner(customer_id)
