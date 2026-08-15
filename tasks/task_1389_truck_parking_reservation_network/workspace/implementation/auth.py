"""Authentication / authorization helpers (PRD §2.1, §2.7 steps 1-2)."""
from flask import request

import errors

ROLES = {"Anonymous", "Driver", "FleetManager", "SiteOperator", "NetworkAdmin"}
ENTITY_BACKED = {"Driver", "FleetManager"}


class Identity:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    def __repr__(self):
        return f"Identity({self.role}, {self.user_id})"


def identity():
    """Priority 1: X-User-Role present and declared; X-User-ID present for
    entity-backed roles (Driver, FleetManager)."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    user_id = request.headers.get("X-User-ID")
    if role in ENTITY_BACKED and not user_id:
        raise errors.unauthenticated()
    return Identity(role, user_id)


def require_roles(ident, roles):
    """Priority 2a: role permitted on the endpoint."""
    if ident.role not in roles:
        raise errors.forbidden()
