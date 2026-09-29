"""Authentication and role authorization (PRD 2.1, ladder steps 1 and 2)."""
import functools

from flask import g, request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "QaSupervisor",
    "QaReviewer",
    "MedicalDirector",
    "AccreditationOfficer",
    "Dispatcher",
)

ALL_OPERATORS = (
    "ProgramAdmin",
    "QaSupervisor",
    "QaReviewer",
    "MedicalDirector",
    "AccreditationOfficer",
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*roles):
    """Decorator enforcing ladder step 1 then step 2 for one endpoint."""

    def wrapper(view):
        @functools.wraps(view)
        def inner(*args, **kwargs):
            _, role = authenticate()
            if role not in roles:
                fail(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not call this endpoint." % role,
                )
            return view(*args, **kwargs)

        return inner

    return wrapper
