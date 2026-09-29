"""Auth header extraction, role checking and organizer-identity resolution."""
from flask import g, request

import db
from errors import err

ROLES = (
    "CharterCounsel",
    "LeadOrganizer",
    "IndependentDirector",
    "CharteringExaminer",
    "InsuranceExaminer",
    "EscrowAgent",
    "PlatformAdmin",
)

ALL_ROLES = list(ROLES)

ORGANIZER_ROLES = ("LeadOrganizer", "IndependentDirector")


def authenticate(allowed_roles):
    """Band 1: ERR_UNAUTHENTICATED then ERR_ROLE_NOT_PERMITTED, in that order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise err("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise err("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_organizer_identity(group_id):
    """Band 1, priority 3.  Enforced on the write endpoints that the two
    entity-backed roles own; the group in scope is supplied by the caller."""
    role = getattr(g, "user_role", None)
    if role not in ORGANIZER_ROLES:
        return None
    organizer = db.get("organizers", g.user_id)
    if organizer is None:
        raise err("ERR_ORGANIZER_IDENTITY_MISMATCH")
    if group_id is not None and organizer["group_id"] != group_id:
        raise err("ERR_ORGANIZER_IDENTITY_MISMATCH")
    return organizer
