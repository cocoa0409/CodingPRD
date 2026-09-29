"""Authentication, role authorization and ownership scope (PRD 2.1, rules 1/2/16)."""

import functools

from flask import g, request

from errors import ApiError, fail

ROLES = ("PlatformAdmin", "BenefitAdministrator", "Employee", "SchoolPartner", "Coach")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role is not a recognized role")
    return user_id, role


def endpoint(roles):
    """Rule 1 then rule 2, for every endpoint."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403, "role %s may not call this endpoint" % role)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def deny():
    fail("ERR_UNAUTHORIZED", "acting principal is outside its ownership scope")


def employer_scope(employer_id):
    if g.role == "BenefitAdministrator" and g.user_id != employer_id:
        deny()


def employee_scope(employee_id):
    if g.role == "Employee" and g.user_id != employee_id:
        deny()


def school_scope(school_id):
    if g.role == "SchoolPartner" and g.user_id != school_id:
        deny()
