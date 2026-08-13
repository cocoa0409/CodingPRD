"""Auth extraction and role checking (PRD §2.1, validation priorities 1-3).

Every request carries X-User-ID and X-User-Role. Roles are exactly
CustomerCareManager, CustomerCareRep, Homebuyer.
"""
from flask import request

from errors import err_unauthenticated, err_forbidden

ROLE_MANAGER = "CustomerCareManager"
ROLE_REP = "CustomerCareRep"
ROLE_BUYER = "Homebuyer"
DECLARED_ROLES = {ROLE_MANAGER, ROLE_REP, ROLE_BUYER}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def current_actor():
    """Validation priority 1: authentication."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in DECLARED_ROLES or user_id is None:
        raise err_unauthenticated()
    return Actor(user_id, role)


def require_roles(*roles):
    """Priorities 1+2: authentication, then role authorization."""
    actor = current_actor()
    if actor.role not in roles:
        raise err_forbidden("Role %s is not permitted for this operation." % actor.role)
    return actor


def check_buyer_ownership(actor, home):
    """Priority 3: entity-backed ownership for buyer-scoped operations."""
    if home["primary_buyer_id"] != actor.user_id:
        raise err_forbidden("X-User-ID does not match the home's primary buyer.")
