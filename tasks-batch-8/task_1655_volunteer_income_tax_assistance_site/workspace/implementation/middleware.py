"""Auth (PRD §2.1, pipeline tier 1-2): header extraction, role gating, site binding."""
from flask import request, g

from db import store
from errors import ApiError

ROLES = ["SiteCoordinator", "Preparer", "QualityReviewer", "Screener", "SponsorAdmin"]

# Roles whose X-User-ID must reference an existing Volunteer; SponsorAdmin is opaque.
ENTITY_BACKED = {"SiteCoordinator", "Preparer", "QualityReviewer", "Screener"}


def get_context():
    """Validate the two auth headers; returns (user_id, role, volunteer_or_none)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER", 401,
                       "X-User-ID and X-User-Role headers are required and the role "
                       "must be one of the declared roles")
    volunteer = None
    if role in ENTITY_BACKED:
        volunteer = store.volunteers.get(uid)
        if volunteer is None:
            raise ApiError("ERR_MISSING_AUTH_HEADER", 401,
                           "X-User-ID does not reference an existing Volunteer")
    g.user_id = uid
    g.user_role = role
    g.volunteer = volunteer
    return uid, role, volunteer


def require_roles(allowed):
    role = getattr(g, "user_role", None)
    if role is None:
        get_context()
        role = g.user_role
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role %s is not permitted on this endpoint" % role)


def require_site_coordinator_of(site_id):
    """SiteCoordinator acting on an operation addressed to a specific site must be
    a coordinator-flagged volunteer of that site (PRD §2.1, pipeline tier 2)."""
    require_roles(["SiteCoordinator"])
    v = g.volunteer
    if not v.get("is_coordinator") or v.get("site_id") != site_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "SiteCoordinator must belong to and be a coordinator of this site")
