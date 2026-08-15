"""Auth middleware: extracts X-User-ID / X-User-Role, enforces RBAC.

Per PRD §2.1, the seven roles are PlatformAdmin, TalentManager, BrandManager,
ComplianceOfficer, FinanceAdmin, Creator, Brand. Creator/Brand are
entity-backed: X-User-ID is the id of the acting Creator/Brand record and
ownership checks compare resource.creator_id / resource.brand_id against it.
The other roles are opaque operator identifiers.
"""

import functools

from flask import request

import errors as err

ROLES = {
    "PlatformAdmin",
    "TalentManager",
    "BrandManager",
    "ComplianceOfficer",
    "FinanceAdmin",
    "Creator",
    "Brand",
}

ENTITY_BACKED = {"Creator", "Brand"}


class Actor:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in ENTITY_BACKED


def get_actor() -> Actor:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err.unauthenticated()
    return Actor(user_id, role)


def require_roles(*roles):
    """Decorator: priority 1 (auth) then priority 2 (role authorization)."""
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            actor = get_actor()
            if actor.role not in allowed:
                raise err.forbidden()
            return fn(actor, *args, **kwargs)

        return wrapper

    return decorator


def require_owner(actor: Actor, owner_id, what="resource"):
    """Priority-3 ownership check for entity-backed roles."""
    if actor.is_entity_backed and actor.user_id != owner_id:
        raise err.forbidden(f"Caller does not own this {what}")
