"""Auth header extraction and role gating (PRD section 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError

CAPITAL_PLANNER = "CapitalPlanner"
CLINICAL_REQUESTER = "ClinicalRequester"
FACILITY_DIRECTOR = "FacilityDirector"
COMMITTEE_MEMBER = "CommitteeMember"
COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = (
    CAPITAL_PLANNER,
    CLINICAL_REQUESTER,
    FACILITY_DIRECTOR,
    COMMITTEE_MEMBER,
    COMPLIANCE_AUDITOR,
)


def guard(*roles):
    """X-User-ID presence (401) then role authorization (403), in that order."""

    allowed = roles if roles else ALL_ROLES

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            if user_id is None or user_id.strip() == "":
                raise ApiError("ERR_USER_CONTEXT_REQUIRED")
            role = request.headers.get("X-User-Role")
            if role is None or role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
