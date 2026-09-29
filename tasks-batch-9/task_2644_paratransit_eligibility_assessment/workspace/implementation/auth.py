"""PRD 2.5 stages 1-5 — authentication, role authorization, applicant ownership,
actor-identity usability and assigned-reviewer authorization.

PRD 2.1 fixes the two headers: X-User-ID identifies the acting user and
X-User-Role names the role.  For an Applicant, X-User-ID is the id of the
acting Applicant record; for the seven staff roles it is an opaque operator
identifier that is never resolved to a stored row.
"""

from functools import wraps

from flask import g, request

from errors import ApiError
from shapes import ROLES
from store import db

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

APPLICANT_ROLE = "Applicant"


def actor_id():
    return g.get("actor_id")


def actor_role():
    return g.get("actor_role")


def _authenticate():
    """Stage 1.  Both headers present and the role among the eight declared names."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.actor_id = user_id
    g.actor_role = role
    return user_id, role


def _authorize(role, allowed_roles):
    """Stage 2.  The acting role is listed for the addressed operation."""
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def _check_ownership(user_id, resolver, kwargs):
    """Stage 3.  Guards exactly the fifteen operations enumerated in PRD 2.1.

    A resolver returning None means the owning applicant could not be
    determined (the addressed record or body reference does not exist), so
    ownership cannot be violated and the request falls through to the
    stage 6/7 not-found.
    """
    owner_id = resolver(kwargs)
    if owner_id is None:
        return
    if owner_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def _check_identity_usable(user_id):
    """Stage 4.  On the five segregated-step operations the acting identity must
    be usable for the independence comparison."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A usable acting identity is required for this operation.",
        )


def _check_assigned_reviewer(user_id, kwargs):
    """Stage 5.  Opening the review and recording the decision are reserved to
    the appeal's assigned reviewer."""
    appeal_id = kwargs.get("appeal_id")
    appeal = db.appeals.get(appeal_id) if isinstance(appeal_id, str) else None
    if appeal is None:
        return
    if appeal.get("reviewer_user_id") != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_REVIEWER")


def require(roles, ownership=None, identity_required=False, assigned_reviewer=False):
    """Screen a request through PRD 2.5 stages 1-5, in that exact order."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = _authenticate()
            _authorize(role, roles)
            if ownership is not None and role == APPLICANT_ROLE:
                _check_ownership(user_id, ownership, kwargs)
            if identity_required:
                _check_identity_usable(user_id)
            if assigned_reviewer:
                _check_assigned_reviewer(user_id, kwargs)
            return view(*args, **kwargs)

        return wrapper

    return decorator
