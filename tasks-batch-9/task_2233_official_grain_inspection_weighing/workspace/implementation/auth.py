"""Authentication, RBAC and applicant scoping (PRD §2.1, ladder rungs 1, 2, 4)."""

import functools

from flask import g, request

from errors import ApiError
from store import db

SERVICE_ADMIN = "ServiceAdmin"
SUPERVISING_INSPECTOR = "SupervisingInspector"
LICENSED_INSPECTOR = "LicensedInspector"
APPLICANT_USER = "ApplicantUser"
AUDITOR = "Auditor"

ANY_ROLE = (SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, APPLICANT_USER, AUDITOR)

CANONICAL_USERS = {
    "admin_user": SERVICE_ADMIN,
    "supervisor_user": SUPERVISING_INSPECTOR,
    "inspector_user": LICENSED_INSPECTOR,
    "applicant_user": APPLICANT_USER,
    "auditor_user": AUDITOR,
}


def authenticate():
    """Rung 1 — resolve X-User-Id to a role, else ERR_UNAUTHENTICATED."""
    raw = request.headers.get("X-User-Id")
    if raw is None or not str(raw).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(raw).strip()
    g.user_id = user_id
    g.acting_applicant_id = None
    if user_id in CANONICAL_USERS:
        g.role = CANONICAL_USERS[user_id]
        return g.role
    # PRD §2.1: when the header value is itself the id of an existing Applicant
    # row, that row is the acting account.
    if user_id in db.applicants:
        g.role = APPLICANT_USER
        g.acting_applicant_id = user_id
        return g.role
    # An Inspector id identifies the licensed operator behind the call; the role
    # follows the endorsements they hold.
    inspector = db.inspectors.get(user_id)
    if inspector is not None:
        g.role = (
            SUPERVISING_INSPECTOR
            if "SUPERVISION" in inspector.get("endorsements", [])
            else LICENSED_INSPECTOR
        )
        return g.role
    raise ApiError("ERR_UNAUTHENTICATED")


def authorize(roles):
    """Rung 2 — the resolved role must be permitted for the endpoint."""
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")


def role():
    return g.get("role")


def acting_applicant_id():
    return g.get("acting_applicant_id")


def assert_applicant_scope(applicant_id):
    """Rung 4 — an ApplicantUser may only touch their own account's rows."""
    acting = acting_applicant_id()
    if acting is None:
        return
    if applicant_id is not None and applicant_id != acting:
        raise ApiError("ERR_APPLICANT_SCOPE_VIOLATION")


def endpoint(roles):
    """Decorator applying rung 1 then rung 2 before the handler body."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return func(*args, **kwargs)

        return wrapper

    return decorator
