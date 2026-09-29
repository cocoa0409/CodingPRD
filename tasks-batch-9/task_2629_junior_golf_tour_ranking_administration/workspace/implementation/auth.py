"""Authentication, authorization and ownership helpers."""
from flask import request

from errors import ApiError
from store import db, clock, dt_of

ROLES = (
    "TourAdmin",
    "RulesOfficial",
    "ChiefReferee",
    "ConductCommittee",
    "Member",
    "Coach",
    "Anonymous",
)

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_coach(self):
        return self.role == "Coach"


def authenticate(public=False):
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)
    if role is None or role not in ROLES:
        if not public:
            raise ApiError("ERR_UNAUTHENTICATED")
        if role is None:
            role = "Anonymous"
    return Caller(role, user_id)


def guard(allowed_roles, public=False):
    """Authenticate then authorize. Authorization applies to every endpoint."""
    caller = authenticate(public=public)
    if caller.role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this operation" % caller.role,
        )
    return caller


def live_coach_grant(caller, member_id):
    """The coach's GRANTED, unexpired grant on this junior, or None."""
    now = clock()
    for grant in db.coach_access_grants.values():
        if grant["member_id"] != member_id:
            continue
        if grant["coach_user_id"] != caller.user_id:
            continue
        if grant["status"] != "GRANTED":
            continue
        expires = dt_of(grant["expires_at"])
        if expires is None or not (expires > now):
            continue
        return grant
    return None


def require_member_ownership(caller, member_id, error_id="ERR_FORBIDDEN_RESOURCE"):
    """A Member caller may only reach its own rows."""
    if caller.is_member and caller.user_id != member_id:
        raise ApiError(error_id)


def require_member_read_access(caller, member_id, coach_error="ERR_FORBIDDEN_RESOURCE"):
    """Ownership for a Member caller, live grant for a Coach caller."""
    require_member_ownership(caller, member_id)
    if caller.is_coach and live_coach_grant(caller, member_id) is None:
        raise ApiError(coach_error)
