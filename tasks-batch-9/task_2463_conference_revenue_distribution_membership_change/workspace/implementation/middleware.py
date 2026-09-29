"""Authentication, role authorisation and member ownership (PRD section 2.1).

The ladder implemented here is the head of PRD section 2.8:

  1. authentication            -> ERR_UNAUTHENTICATED
  2. role authorisation        -> ERR_UNAUTHORIZED
  3. member ownership          -> ERR_NOT_MEMBER_OWNER
  4. conference initialisation -> ERR_CONFERENCE_NOT_INITIALIZED
"""

import functools

from flask import request

from db import db
from errors import ApiError

ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "ScheduleCoordinator",
    "PlatformAdmin",
    "MemberRepresentative",
)

MEMBER_REPRESENTATIVE = "MemberRepresentative"


def current_user_id():
    return request.headers.get("X-User-ID")


def current_role():
    return request.headers.get("X-User-Role")


def authenticate():
    user_id = current_user_id()
    role = current_role()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")


def authorize(allowed_roles):
    if allowed_roles is None:
        return
    if current_role() not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")


def require_conference():
    if db.conference is None:
        raise ApiError("ERR_CONFERENCE_NOT_INITIALIZED")
    return db.conference


def raw_body():
    """Best-effort JSON body; a malformed body behaves as an empty object."""
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return body


def own_path_member(**kwargs):
    """A MemberRepresentative may only address its own member id in the path."""
    if current_role() != MEMBER_REPRESENTATIVE:
        return
    member_id = kwargs.get("member_id")
    if member_id is not None and current_user_id() != member_id:
        raise ApiError("ERR_NOT_MEMBER_OWNER")


def own_body_member(**kwargs):
    """A MemberRepresentative may only cast a ballot for its own member id."""
    if current_role() != MEMBER_REPRESENTATIVE:
        return
    body = raw_body()
    member_id = body.get("member_id")
    if isinstance(member_id, str) and current_user_id() != member_id:
        raise ApiError("ERR_NOT_MEMBER_OWNER")


def own_appearance_member(**kwargs):
    """A MemberRepresentative may only resubmit its own appearance."""
    if current_role() != MEMBER_REPRESENTATIVE:
        return
    appearance = db.bowl_appearances.get(kwargs.get("appearance_id"))
    if appearance is not None and current_user_id() != appearance["member_id"]:
        raise ApiError("ERR_NOT_MEMBER_OWNER")


def api(roles, owner=None, needs_conference=True):
    """Wrap a view so the ladder's first four rungs run in the PRD's order."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(**kwargs):
            authenticate()
            authorize(roles)
            if owner is not None:
                owner(**kwargs)
            if needs_conference:
                require_conference()
            return view(**kwargs)

        return wrapper

    return decorator
