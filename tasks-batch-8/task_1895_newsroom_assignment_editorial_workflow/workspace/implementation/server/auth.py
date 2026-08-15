"""Authentication and role authorization per PRD section 2.1.

Header roles (CamelCase, from X-User-Role):
  Reporter, Photographer, CopyEditor, FactChecker, LegalReviewer,
  AssignmentEditor, ManagingEditor, NewsDirector, AnalyticsProducer

NewsDirector is an opaque operator identity (no StaffMember row needed).
All other roles are entity-backed: X-User-ID must resolve to an existing
StaffMember.
"""

from flask import request

from .errors import ApiError
from .store import STORE

ROLES = {
    "Reporter",
    "Photographer",
    "CopyEditor",
    "FactChecker",
    "LegalReviewer",
    "AssignmentEditor",
    "ManagingEditor",
    "NewsDirector",
    "AnalyticsProducer",
}

ENTITY_BACKED_ROLES = ROLES - {"NewsDirector"}

ALL_ROLES = sorted(ROLES)


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or malformed X-User-Role / X-User-ID headers",
        )
    if role in ENTITY_BACKED_ROLES and uid not in STORE.staff:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID does not resolve to an existing staff member",
        )
    return uid, role


def require(allowed_roles):
    """Priority 1 (authentication) then priority 2 (role authorization)."""
    uid, role = auth()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN", 403, f"Role {role} is not permitted for this endpoint"
        )
    return uid, role


def require_owner(uid, owner_id):
    if uid != owner_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Ownership check failed")
