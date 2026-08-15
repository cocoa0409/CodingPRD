"""Auth middleware (PRD §2.1, SCAFFOLD validations priority 1-2).

Every request must carry X-User-Role naming one of: Court, Receiver, Creditor,
SystemAdmin. X-User-ID is an opaque operator identifier, never compared to any
entity id. Authentication (401) is always evaluated before authorization (403),
and both precede every request-shape, existence, state, or fiscal check.
"""
from flask import request

import errors

ROLES = ("Court", "Receiver", "Creditor", "SystemAdmin")


def get_role():
    """Return the caller's role, or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise errors.err_unauthenticated()
    return role


def require_roles(*allowed):
    """Authenticate, then authorize the acting role for this endpoint."""
    role = get_role()
    if role not in allowed:
        raise errors.err_forbidden()
    return role
