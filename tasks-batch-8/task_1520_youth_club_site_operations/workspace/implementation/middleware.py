"""Auth (PRD §2.1, validation pipeline stage 1) and role authorization (stage 2)."""

from flask import request

import db
from errors import err

ALL_ROLES = ["PlatformAdmin", "SiteDirector", "FrontlineStaff", "StateAgencyReviewer", "FunderContact"]
ENTITY_BACKED = {"SiteDirector": "DIRECTOR", "FrontlineStaff": "FRONTLINE"}


def authenticate():
    """Stage 1: ERR_UNAUTHENTICATED on missing/unknown headers or unresolved
    entity-backed identity."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ALL_ROLES or not user_id:
        raise err("ERR_UNAUTHENTICATED",
                  "X-User-Role must be one of %s and X-User-ID must be present" % ALL_ROLES)
    if role in ENTITY_BACKED:
        staff = db.get("staff", user_id)
        if staff is None or staff.get("position") != ENTITY_BACKED[role] or staff.get("status") != "ACTIVE":
            raise err("ERR_UNAUTHENTICATED",
                      "entity-backed role %s requires X-User-ID of a matching ACTIVE Staff row" % role)
    return role, user_id


def authorize(role, allowed):
    """Stage 2: ERR_UNAUTHORIZED_ROLE when the role is not in the endpoint list."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE", "role %s is not authorized for this endpoint" % role)
