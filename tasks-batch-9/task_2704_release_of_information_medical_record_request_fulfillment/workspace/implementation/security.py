"""Authentication, role authorization and requester ownership (PRD 2.1, priorities 1-3)."""

from flask import request

from errors import ApiError

STAFF = [
    "PlatformAdmin", "FacilityAdmin", "IntakeSpecialist", "RecordsAnalyst",
    "ReleaseReviewer", "BillingClerk", "PrivacyOfficer",
]
ALL_ROLES = STAFF + ["Requester"]


def actor(roles):
    """Priority 1 then priority 2.  Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    if uid is None or uid.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return uid, role


def own_request(role, uid, req):
    """Priority 3.  A missing entity is skipped so the 404 at priority 6 wins."""
    if role != "Requester":
        return
    if req is None:
        return
    if req.get("requester_id") != uid:
        raise ApiError("ERR_NOT_REQUEST_OWNER")


def own_authorization(role, uid, auth):
    if role != "Requester":
        return
    if auth is None:
        return
    if auth.get("requester_id") != uid:
        raise ApiError("ERR_NOT_REQUEST_OWNER")
