"""Authentication and role entitlement (PRD §2.1, ladder steps 1-3)."""
from flask import g, request

import constants
from errors import ApiError


def authenticate():
    """Ladder step 1 — both headers present, role one of the five spellings."""
    user_id = request.headers.get(constants.HEADER_USER_ID)
    role = request.headers.get(constants.HEADER_USER_ROLE)
    if not user_id or not role or role not in constants.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def current_role():
    return getattr(g, "role", None)


def current_user_id():
    return getattr(g, "user_id", None)


def require_roles(*roles):
    """Ladder step 2 — the acting role may invoke this endpoint at all."""
    if current_role() not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def require_discriminator_role(value, mapping):
    """Ladder step 2 — on a shared dispatcher the discriminator must belong to
    the acting role.  An unrecognised discriminator is left to the shape check."""
    if not isinstance(value, str):
        return
    owner = mapping.get(value)
    if owner is None:
        return
    if current_role() != owner:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def require_association_scope(association_id):
    """Ladder step 2 — a TransitionCommittee acts only for its own association."""
    if current_role() != constants.ROLE_TRANSITION_COMMITTEE:
        return
    if not isinstance(association_id, str) or not association_id:
        return
    if current_user_id() != association_id:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
