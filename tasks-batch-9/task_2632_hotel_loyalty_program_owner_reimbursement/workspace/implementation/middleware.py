"""Authentication, role authorisation and resource-ownership enforcement.

PRD section 2.1: every request carries X-User-ID and X-User-Role.  A missing
header or an unrecognised role is ERR_UNAUTHENTICATED (401); a recognised role
that is not permitted is ERR_UNAUTHORIZED (403); a caller reaching a property or
a member other than the one its X-User-ID names is ERR_FORBIDDEN_RESOURCE_OWNER
(403).
"""

from flask import request

from errors import ApiError

ADMIN = "ProgramAdministrator"
OWNER = "HotelOwner"
MEMBER = "Member"
AGENT = "MemberCareAgent"
AUDITOR = "ProgramAuditor"

ALL_ROLES = (ADMIN, OWNER, MEMBER, AGENT, AUDITOR)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_owner(self):
        return self.role == OWNER

    @property
    def is_member(self):
        return self.role == MEMBER


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Caller(str(user_id).strip(), role)


def require(*allowed_roles):
    """Authenticate then authorise in the PRD's fixed order."""
    caller = authenticate()
    if caller.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return caller


def own_hotel(caller, hotel_id):
    """A HotelOwner may only reach the property its X-User-ID names."""
    if caller.is_owner and caller.user_id != hotel_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")


def own_member(caller, member_id):
    """A Member may only reach its own member record and descendants."""
    if caller.is_member and caller.user_id != member_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")


def scope_filter(caller, args, hotel_key="hotel_id", member_key="member_id"):
    """Collection scoping for owner-bound roles.

    An explicit filter naming somebody else's property or member reaches that
    resource and is refused; with no filter the collection is silently narrowed
    to the caller's own rows.
    """
    if caller.is_owner and hotel_key is not None:
        requested = args.get(hotel_key)
        if requested is not None and requested != caller.user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")
    if caller.is_member and member_key is not None:
        requested = args.get(member_key)
        if requested is not None and requested != caller.user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER")
