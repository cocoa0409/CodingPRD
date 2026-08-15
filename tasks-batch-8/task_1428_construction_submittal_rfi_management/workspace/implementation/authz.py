"""Authentication / authorization helpers (PRD 2.1, validations priorities 1-3)."""
from flask import request

from errors import missing_user_context, forbidden_role

ROLES = (
    "PlatformAdmin",
    "ProjectManager",
    "ProjectEngineer",
    "Reviewer",
    "SubcontractorRep",
    "OwnerRep",
)

PLATFORM_ADMIN = "PlatformAdmin"
PROJECT_MANAGER = "ProjectManager"
PROJECT_ENGINEER = "ProjectEngineer"
REVIEWER = "Reviewer"
SUBCONTRACTOR_REP = "SubcontractorRep"
OWNER_REP = "OwnerRep"

ALL_ROLES = list(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip() or role not in ROLES:
        raise missing_user_context()
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: header presence/validity, then endpoint role membership."""
    uid, role = authenticate()
    if role not in role_list:
        raise forbidden_role()
    return uid, role
