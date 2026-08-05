"""Validation ladder rungs 1, 2 and 7 (PRD 2.1 and 2.7).

Rung 1  authentication     ERR_UNAUTHENTICATED   401
Rung 2  role authorisation ERR_FORBIDDEN_ROLE    403
Rung 7  resource ownership ERR_NOT_RESOURCE_OWNER 403
"""
from flask import g, request

import constants as C
from errors import ApiError
from store import db


def authenticate():
    """RUNG 1 — both headers present and the role one of the five declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in C.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    if not hasattr(g, "touched"):
        g.touched = set()
    return user_id, role


def authorize(allowed_roles):
    """RUNG 2 — the acting role appears in the endpoint's authorised-role list."""
    if g.role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def begin(allowed_roles):
    authenticate()
    authorize(allowed_roles)


# ------------------------------------------------------------ RUNG 7 --------
def _family_of_membership(membership):
    return membership["family_id"] if membership else None


def require_family_owner(family_id):
    """Parent ownership: X-User-ID is the id of the acting Family row."""
    if g.role != C.ROLE_PARENT:
        return
    if family_id != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_child_owner(child):
    if g.role != C.ROLE_PARENT:
        return
    require_family_owner(child["family_id"] if child else None)


def require_membership_owner(membership):
    if g.role != C.ROLE_PARENT:
        return
    require_family_owner(_family_of_membership(membership))


def require_physician_clinical_owner(membership):
    """The Physician rung binds exactly four clinical writes: well-visit
    completion, encounter clinical completion, encounter cancel and form
    issuance.  On those, membership.physician_id must equal X-User-ID."""
    if g.role != C.ROLE_PHYSICIAN:
        return
    if membership is None or membership["physician_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def parent_family_scope():
    """List endpoints: a Parent reads only their own household's rows."""
    if g.role == C.ROLE_PARENT:
        return g.user_id
    return None


def membership_family_id(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None
