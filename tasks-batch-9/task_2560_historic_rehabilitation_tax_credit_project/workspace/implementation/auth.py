"""Authentication, role authorization and actor-identity resolution (PRD 2.1)."""

from flask import request

from db import store
from errors import ApiError

ROLES = (
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
    "InvestorAdmin",
    "PlatformAdmin",
)

ROLE_AGENCY = {"ShpoReviewer": "SHPO", "NpsReviewer": "NPS"}


def caller_id():
    """Band 1: X-User-ID present and non-empty."""
    value = request.headers.get("X-User-ID")
    if value is None or value.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    return value


def caller_role():
    return request.headers.get("X-User-Role")


def require(*allowed):
    """Bands 1 and 2, in that order. Returns (user_id, role)."""
    uid = caller_id()
    role = caller_role()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return uid, role


def acting_reviewer(uid, agency):
    """Band 6: the acting principal is an ACTIVE Reviewer of the given agency."""
    reviewer = store.reviewers.get(uid)
    if reviewer is None:
        raise ApiError("ERR_UNAUTHORIZED", "The caller is not a registered reviewer.")
    if reviewer["agency"] != agency:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "A reviewer of agency %s may not record this decision." % reviewer["agency"],
        )
    if reviewer["credential_status"] != "ACTIVE":
        raise ApiError("ERR_UNAUTHORIZED", "The acting reviewer's credential is not ACTIVE.")
    return reviewer


def acting_interest(uid, project_id=None):
    """Band 6: the acting InvestorAdmin resolves to an ADMITTED interest."""
    interest = store.investor_interests.get(uid)
    if interest is None or interest["status"] != "ADMITTED":
        raise ApiError("ERR_INVESTOR_NOT_ADMITTED")
    if project_id is not None and interest["project_id"] != project_id:
        raise ApiError("ERR_INVESTOR_NOT_ADMITTED")
    return interest


def own_project(project, uid):
    """Band 6: developer ownership of the target project."""
    if project["developer_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "The acting developer does not own this project.")
    return project
