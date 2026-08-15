"""Auth header extraction and role checking (PRD §2.1, validations 1-2)."""
from flask import request

from db import db
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin",
    "RegulatoryAffairsManager",
    "RemediationOwner",
    "ComplianceReviewer",
    "BoardReporter",
}


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "missing or malformed X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "role %s is not permitted to invoke this endpoint" % role)


def reviewer_gate(uid):
    """Entity-backed identity for ComplianceReviewer: an existing reviewer
    record whose active flag is false may not perform any review action.
    Unknown ids pass through as opaque reviewer identities (PRD §2.10 SoD
    comparisons evaluate the raw acting id)."""
    rev = db.reviewers.get(uid)
    if rev is not None and not rev.get("active", True):
        raise ApiError(ERR_UNAUTHORIZED, 403, "inactive reviewer may not perform reviews")
    return rev
