"""Caller identity and role based access control (PRD section 2.1)."""

from flask import request

from errors import ApiError

STAFF_ROLES = [
    "MetallurgyEngineer",
    "GeometryEngineer",
    "CoatingEngineer",
    "ApplicationEngineer",
    "QualityApprover",
    "ProductionPlanner",
]
ALL_ROLES = STAFF_ROLES + ["Customer"]


def caller_id():
    return request.headers.get("X-User-ID")


def caller_role():
    return request.headers.get("X-User-Role")


def authenticate(allowed_roles):
    """Priority 1 (authentication) then priority 2 (authorisation)."""
    uid = caller_id()
    if uid is None or uid.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The X-User-ID header is absent or empty.")
    role = caller_role()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %r is not authorised for this endpoint." % (role,),
        )
    return uid, role


def authenticate_clock():
    """The logical clock endpoint is the single exception to the identity rule."""
    role = caller_role()
    if role is not None and role != "" and role not in STAFF_ROLES:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %r is not authorised for this endpoint." % (role,),
        )
    return caller_id(), role
