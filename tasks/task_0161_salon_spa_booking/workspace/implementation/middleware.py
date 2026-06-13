"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.7).

Headers (PRD §2.1):
    X-User-ID    — acting user identity
    X-User-Role  — one of {SalonOwner, FrontDesk, Stylist, Client}

For Stylist / Client, X-User-ID is the id of the acting entity (entity-backed
ownership). For SalonOwner / FrontDesk, X-User-ID is opaque.
"""
from flask import request

from errors import err

ROLES = {"SalonOwner", "FrontDesk", "Stylist", "Client"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the two mandatory headers. Priority 1 (ERR_UNAUTHENTICATED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid auth headers")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Priority 2 (ERR_FORBIDDEN): the acting role must be permitted."""
    if caller.role not in allowed:
        raise err("ERR_FORBIDDEN", f"Role {caller.role} may not perform this operation")


def require_owns_client(caller, client_id):
    """Entity-backed ownership for the Client role (PRD §2.1).

    When the caller is a Client, X-User-ID must equal the client_id the
    operation targets; otherwise ERR_FORBIDDEN. No-op for opaque roles
    (SalonOwner / FrontDesk) and for Stylist (which does not act on clients).
    """
    if caller.role == "Client" and caller.user_id != client_id:
        raise err("ERR_FORBIDDEN", "client may only act on its own resources")


def require_owns_stylist(caller, stylist_id):
    """Entity-backed ownership for the Stylist role (PRD §2.1)."""
    if caller.role == "Stylist" and caller.user_id != stylist_id:
        raise err("ERR_FORBIDDEN", "stylist may only act on its own resources")
