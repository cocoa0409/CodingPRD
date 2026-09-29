"""Stages 1 and 2 of the admission ladder (PRD section 2.1, section 2.5)."""

import functools

from flask import request

from errors import fail

ROLES = (
    "Student",
    "FacultyMember",
    "GradSchoolAnalyst",
    "GraduateDean",
    "IntegrityOfficer",
    "Registrar",
)

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role" % role)
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        fail(
            "ERR_UNAUTHORIZED_ROLE",
            "Role '%s' may not perform this operation" % role,
        )


def endpoint(allowed_roles):
    """Wrap a handler so that stages 1 and 2 always run first, in order."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(**kwargs):
            user_id, role = authenticate()
            authorize(role, allowed_roles)
            return view(user_id, role, **kwargs)

        return wrapper

    return decorator
