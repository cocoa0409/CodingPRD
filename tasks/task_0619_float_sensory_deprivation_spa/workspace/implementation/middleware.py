"""Auth header extraction + RBAC. Headers: X-User-ID, X-User-Role (PRD §2.1).

Roles: Member, FrontDesk, Admin (hierarchical override).
"""
from flask import request

import errors
from constants import ROLES

ROLE_RANK = {"Member": 1, "FrontDesk": 2, "Admin": 3}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_member(self):
        return self.role == "Member"

    def rank(self):
        return ROLE_RANK[self.role]


def authenticate():
    """Validate the two mandatory headers. Raise ERR_UNAUTHENTICATED on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Hierarchical override: a wider role may do anything a narrower role may.

    `allowed_roles` is the set of roles explicitly listed for the endpoint. A
    principal is permitted if its rank is >= the minimum rank among the allowed
    roles (i.e. it sits at or above the narrowest permitted role).
    """
    if principal.role in allowed_roles:
        return
    min_rank = min(ROLE_RANK[r] for r in allowed_roles)
    if principal.rank() >= min_rank:
        return
    raise errors.forbidden()
