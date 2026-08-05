"""Authentication (ladder step 1) and authorization (ladder step 2)."""

from flask import g, request

from errors import ApiError

ROLES = ("IntakeOfficer", "SupervisingOfficer", "JudicialOfficer",
         "ProgramAdmin", "Defendant")


def authenticate():
    """Ladder step 1.  Populates g.role / g.user_id."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role is missing or unrecognised.")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID is required.")
    g.role = role
    g.user_id = user_id
    return role, user_id


def authorize(*allowed_roles):
    """Ladder step 2."""
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not call this endpoint." % g.role)


def role():
    return getattr(g, "role", None)


def user_id():
    return getattr(g, "user_id", None)
