"""Auth header extraction, role checking and carrier scoping (PRD 2.1, 2.7)."""

from flask import g, request

from consts import ROLES
from errors import fail


def authenticate(*allowed_roles):
    """Band 1 (ERR_UNAUTHENTICATED) then band 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    user_id = user_id.strip() if isinstance(user_id, str) else None
    role = role.strip() if isinstance(role, str) else None
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    allowed = allowed_roles[0] if len(allowed_roles) == 1 and isinstance(allowed_roles[0], (list, tuple)) else allowed_roles
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_carrier_scope(carrier_id):
    """Band 3: a CarrierLiaison acts only inside its own carrier.

    The liaison's X-User-ID *is* the Carrier id. When the guarding carrier id
    cannot be resolved (missing/unknown reference) the check is skipped so the
    later existence bands can report the proper 404.
    """
    if getattr(g, "role", None) != "CarrierLiaison":
        return
    if carrier_id is None:
        return
    if g.user_id != carrier_id:
        fail("ERR_CARRIER_SCOPE_VIOLATION")


def scope_read(carrier_id):
    """PRD 2.1: a CarrierLiaison only ever reads inside its own carrier.

    Reads resolve the row first so an unknown id still reports its own 404;
    only an existing row belonging to another carrier is a scope violation.
    """
    require_carrier_scope(carrier_id)


def liaison_carrier_id():
    """The acting carrier id when the caller is a CarrierLiaison, else None.

    List reads use it to narrow the collection instead of refusing, so a
    liaison simply sees its own rows.
    """
    if getattr(g, "role", None) == "CarrierLiaison":
        return g.user_id
    return None
