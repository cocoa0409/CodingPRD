"""Auth header extraction, role checks, and GroupLeader ownership (PRD 2.1,
validation families 1-2-4 in the order of PRD 2.11).

Roles: ProgramCoordinator (opaque X-User-ID) and GroupLeader (X-User-ID is the
AdopterGroup id returned at registration).
"""
from flask import request

from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_OWNERSHIP,
)

ALL_ROLES = {"ProgramCoordinator", "GroupLeader"}
COORD = "ProgramCoordinator"
LEADER = "GroupLeader"


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Family 1: header presence, non-blank, declared role."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must be present and the role declared")
    return Caller(user_id, role)


def check_role(caller: Caller, allowed_roles):
    """Family 2: the acting role must appear in the endpoint's role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def check_ownership(caller: Caller, owner_group_id):
    """Family 4: a GroupLeader may only touch chains rooted at their own group.

    owner_group_id=None means the resource has no owning group chain (e.g. a
    hazard filed without an event); no ownership restriction applies.
    """
    if caller.role != LEADER:
        return
    if owner_group_id is None:
        return
    if caller.user_id != owner_group_id:
        raise_error(ERR_FORBIDDEN_OWNERSHIP,
                    "resource chain belongs to a different adopter group")


def authorized(allowed_roles, owner_group_id=None) -> Caller:
    caller = get_caller()
    check_role(caller, allowed_roles)
    check_ownership(caller, owner_group_id)
    return caller
