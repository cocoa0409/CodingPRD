"""Authentication, role authorisation and identity-binding scope checks
(PRD 2.1, 2.9 steps 1-3 and 8-12)."""

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "EducationDirector",
    "CurriculumSpecialist",
    "BookingCoordinator",
    "StewardshipManager",
    "GrantsOfficer",
    "Naturalist",
    "TeacherContact",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_teacher(self):
        return self.role == "TeacherContact"

    @property
    def is_naturalist(self):
        return self.role == "Naturalist"


def authorize(allowed_roles):
    """PRD 2.9 checks 1, 2 and 3, in that order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(user_id)
    role = str(role)
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)


# --------------------------------------------------------------------------
# PRD 2.9 step 8 - TeacherContact school scope
# --------------------------------------------------------------------------
def teacher_scope(actor, school_id):
    """The acting teacher must be the school partner the resource belongs to."""
    if not actor.is_teacher:
        return
    if school_id is None or actor.user_id != school_id or actor.user_id not in db.schools:
        raise ApiError("ERR_SCHOOL_SCOPE_VIOLATION")


def teacher_scope_self(actor):
    """For catalog reads guarded by the scope check there is no owning school on
    the resource, so the acting identity itself must name a real school."""
    if not actor.is_teacher:
        return
    if actor.user_id not in db.schools:
        raise ApiError("ERR_SCHOOL_SCOPE_VIOLATION")


# --------------------------------------------------------------------------
# PRD 2.9 step 9 - Naturalist assignment scope
# --------------------------------------------------------------------------
def naturalist_scope(actor, educator_id):
    if not actor.is_naturalist:
        return
    if educator_id is None or actor.user_id != educator_id or actor.user_id not in db.educators:
        raise ApiError("ERR_NOT_ASSIGNED_EDUCATOR")


def naturalist_scope_self(actor):
    if not actor.is_naturalist:
        return
    if actor.user_id not in db.educators:
        raise ApiError("ERR_NOT_ASSIGNED_EDUCATOR")
