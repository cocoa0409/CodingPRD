"""Authentication and role authorization (headers X-User-ID / X-User-Role)."""
from flask import g, request

from errors import err_unauthenticated, err_forbidden

ROLES = ("ProgramAdmin", "IntakeCoordinator", "Volunteer", "Applicant")


def authenticate():
    """Priority 2: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    """Priority 3: role listed for the endpoint."""
    if g.user_role not in roles:
        raise err_forbidden()


def is_applicant():
    return g.user_role == "Applicant"


def is_volunteer():
    return g.user_role == "Volunteer"
