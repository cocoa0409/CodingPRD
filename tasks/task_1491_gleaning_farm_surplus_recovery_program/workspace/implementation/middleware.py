"""Auth header extraction and role checking (PRD §2.1, validations gate 1-2)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "ProgramCoordinator",
    "CrewLeader",
    "Volunteer",
    "FoodSafetyOfficer",
    "GrantReviewer",
}

# Entity-backed roles require X-User-ID; opaque roles do not (PRD §2.1).
ENTITY_BACKED = {"CrewLeader", "Volunteer"}


def actor():
    role = request.headers.get("X-User-Role") or ""
    uid = request.headers.get("X-User-ID") or ""
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or malformed X-User-Role header")
    if role in ENTITY_BACKED and not uid:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID header required for entity-backed roles")
    return role, uid


def require_roles(*allowed):
    role, uid = actor()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Role %s is not permitted to invoke this endpoint" % role)
    return role, uid
