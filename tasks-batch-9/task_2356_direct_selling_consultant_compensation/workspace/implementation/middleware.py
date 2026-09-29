"""Authentication, role authorisation and row-level ownership (PRD 2.1 / 2.8)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "Applicant",
    "Consultant",
    "ComplianceOfficer",
    "CommissionAnalyst",
    "FinanceController",
    "LegalReviewer",
    "PlatformAdmin",
)

ALL_ROLES = ROLES

IDENTITY_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def auth(allowed_roles):
    """Step 1 (credentials) and step 2 (role permitted) of the rejection order."""
    user_id = request.headers.get(IDENTITY_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in tuple(allowed_roles):
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor_id():
    return g.get("user_id")


def actor_role():
    return g.get("role")


def forbidden_resource():
    raise ApiError("ERR_FORBIDDEN_RESOURCE")


def own_consultant(consultant_id):
    """A Consultant caller may only address rows whose consultant_id is theirs."""
    if g.get("role") == "Consultant" and consultant_id != g.get("user_id"):
        forbidden_resource()


def own_application(application):
    """An Applicant caller owns an application whose applicant_email is theirs."""
    if application is None:
        return
    if g.get("role") == "Applicant" and application.get("applicant_email") != g.get("user_id"):
        forbidden_resource()
