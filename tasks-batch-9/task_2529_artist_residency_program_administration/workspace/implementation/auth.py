"""Identity and role-based access control (ladder group 1).

PRD section 2.1: callers identify themselves with X-User-ID and X-User-Role.
The eight declared roles are matched case-sensitively.  Applicant, Panelist and
PanelChair are entity-backed: the acting X-User-ID must resolve to a row of the
backing entity.  PanelChair carries the extra chair_eligible gate, evaluated
immediately after the backing-row check and ahead of any cycle lookup.
"""

from flask import request

from errors import ApiError
from store import ROLE_NAMES, store

ROLE_SET = set(ROLE_NAMES)

BACKING_COLLECTION = {
    "Applicant": "applicants",
    "Panelist": "panelists",
    "PanelChair": "panelists",
}

ENTITY_BACKED_ROLES = ("Applicant", "Panelist", "PanelChair")


class Actor(object):
    __slots__ = ("user_id", "role", "backing")

    def __init__(self, user_id, role, backing):
        self.user_id = user_id
        self.role = role
        self.backing = backing

    @property
    def is_applicant(self):
        return self.role == "Applicant"


def authorize(allowed_roles, chair_eligibility=False):
    """Run the auth ladder and return the acting Actor."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        raise ApiError("ERR_MISSING_USER_ID", "X-User-ID header is required")

    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLE_SET:
        raise ApiError("ERR_INVALID_ROLE", "X-User-Role must be one of the eight declared roles")

    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)

    backing = None
    if any(r in allowed_roles for r in ENTITY_BACKED_ROLES) and role in BACKING_COLLECTION:
        collection = getattr(store, BACKING_COLLECTION[role])
        backing = collection.get(user_id)
        if backing is None:
            raise ApiError("ERR_UNAUTHORIZED",
                           "X-User-ID does not resolve to a %s record" % role)

    if chair_eligibility and role == "PanelChair":
        if backing is None or not backing.get("chair_eligible"):
            raise ApiError("ERR_CHAIR_NOT_ELIGIBLE",
                           "the acting PanelChair is not eligible to chair")

    return Actor(user_id, role, backing)


def require_owner(actor, owner_applicant_id):
    """Ownership gate for entity-backed Applicants (ladder group 5)."""
    if actor.role == "Applicant" and actor.user_id != owner_applicant_id:
        raise ApiError("ERR_UNAUTHORIZED", "an Applicant may only act on their own records")


def require_self_panelist(actor, panelist_id):
    if actor.role in ("Panelist", "PanelChair") and actor.user_id != panelist_id:
        raise ApiError("ERR_UNAUTHORIZED", "a Panelist may only act on their own assignments")
