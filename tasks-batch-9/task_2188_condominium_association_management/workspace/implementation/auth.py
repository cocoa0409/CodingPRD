"""Validation ladder rungs 1-3: headers, endpoint roles, actor recognition (PRD 2.1/2.9)."""
from flask import g, request

import db
from errors import ApiError

ROLES = (
    "CommunityManager",
    "BoardDirector",
    "BoardTreasurer",
    "UnitOwner",
    "InsuranceAdjuster",
    "AssociationAttorney",
    "TitleAgent",
)

ENTITY_BACKED = ("UnitOwner", "BoardDirector", "BoardTreasurer")
BOARD_ROLES = ("BoardDirector", "BoardTreasurer")
SEATED_BOARD_ROLES = ("DIRECTOR", "PRESIDENT", "TREASURER")


def authenticate(allowed_roles):
    """Rungs 1, 2 and 3, in that exact order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # Rung 1 -- headers present and role is one of the seven declared roles.
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    g.user_id = user_id
    g.role = role
    g.actor = None

    # Rung 2 -- the acting role appears in the endpoint's authorized role list.
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    # Rung 3 -- entity-backed roles must resolve to a seated owner row.
    # This applies to EVERY endpoint whose authorized roles include one of the
    # three entity-backed roles, per PRD 2.9 rung 3.
    if role in ENTITY_BACKED:
        owner = db.get("owners", user_id)
        if owner is None:
            raise ApiError("ERR_ACTOR_NOT_RECOGNIZED")
        if role in BOARD_ROLES:
            if not owner.get("is_seated") or owner.get("board_role") in (None, "NONE"):
                raise ApiError("ERR_ACTOR_NOT_RECOGNIZED")
        g.actor = owner
    return role


def actor_id():
    return g.get("user_id")


def role():
    return g.get("role")
