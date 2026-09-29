"""Authentication (priority 1) and authorisation (priority 2)."""

from functools import wraps

from flask import g, request

from errors import ApiError
from store import find

ROLES = (
    "ProgramDirector",
    "Reviewer",
    "Interviewer",
    "CommitteeMember",
    "ProgramCoordinator",
    "Applicant",
    "ComplianceOfficer",
    "NrmpAdmin",
)

# Roles whose X-User-ID is the primary key of a persisted row.
FACULTY_ROLES = ("ProgramDirector", "Reviewer", "Interviewer", "CommitteeMember")


def endpoint(*roles):
    """Bind an endpoint to its authorised role list.

    Priority 1: both headers present and non-empty -> else ERR_UNAUTHENTICATED.
    Priority 2: the role is one of the eight declared names AND is listed on
    this endpoint -> else ERR_FORBIDDEN_ROLE.
    """

    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not user_id.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role is None or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES or role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        wrapper._authorised_roles = allowed
        return wrapper

    return decorator


def acting_id():
    return g.user_id


def acting_role():
    return g.role


def acting_faculty():
    """The FacultyMember the acting identity resolves to, or None."""
    if g.role not in FACULTY_ROLES:
        return None
    return find("faculty_members", g.user_id)


def acting_applicant():
    if g.role != "Applicant":
        return None
    return find("applicants", g.user_id)


def require_acting_faculty():
    faculty = acting_faculty()
    if faculty is None:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return faculty


def require_acting_applicant():
    applicant = acting_applicant()
    if applicant is None:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return applicant


def require_owns_applicant(applicant_id):
    """Priority 8 ownership for an Applicant-acting endpoint."""
    if g.role != "Applicant":
        return
    if g.user_id != applicant_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def require_faculty_program(faculty, program_id):
    if faculty is None or faculty.get("program_id") != program_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def require_program_director(faculty):
    if faculty is None or not faculty.get("is_program_director"):
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
