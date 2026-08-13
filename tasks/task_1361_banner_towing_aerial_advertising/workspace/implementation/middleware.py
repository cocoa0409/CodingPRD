"""Auth header extraction and role checking (PRD section 2.1).

Pipeline order (PRD 2.7): role-header check, then identity-header check, then
per-endpoint role permission check.
"""
from flask import request

from db import DB
from errors import ApiError

ROLES = [
    "PlatformAdmin",
    "Client",
    "Dispatcher",
    "Pilot",
    "GroundCrewLead",
    "ComplianceOfficer",
    "FinanceOfficer",
]

ALL_ROLES = list(ROLES)

# Entity-backed roles: X-User-ID must identify a persisted entity of this type.
ENTITY_BACKED = {"Client": "clients", "Pilot": "pilots"}


def auth(allowed=None):
    """Validate X-User-Role / X-User-ID; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401, "Missing or invalid X-User-Role header"
        )
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID header")
    if role in ENTITY_BACKED and user_id not in DB[ENTITY_BACKED[role]]:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID does not identify a valid persisted %s" % role,
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Role is not permitted for this endpoint"
        )
    return user_id, role


def client_owner_guard(role, user_id, client_id):
    """Entity-backed Client ownership check (PRD 2.1): the resource's client
    foreign key must equal X-User-ID."""
    if role == "Client" and client_id != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER", 403, "Client does not own this resource"
        )


def pilot_owner_guard(role, user_id, pilot_id):
    """Entity-backed Pilot ownership check (PRD 2.1)."""
    if role == "Pilot" and pilot_id is not None and pilot_id != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER", 403, "Pilot does not own this resource"
        )
