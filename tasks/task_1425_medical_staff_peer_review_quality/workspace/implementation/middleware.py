"""Auth header extraction and role checking (PRD section 2.1 / 2.8 stages 1-2)."""
from flask import request

from errors import ApiError

ROLE_NAMES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember", "Provider")


class Actor:
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role


def get_actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    if not user_id or not role or role not in ROLE_NAMES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return Actor(user_id, role)


def require_roles(*roles):
    actor = get_actor()
    if actor.role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE",
            403,
            "role {} is not authorized for this endpoint".format(actor.role),
        )
    return actor
