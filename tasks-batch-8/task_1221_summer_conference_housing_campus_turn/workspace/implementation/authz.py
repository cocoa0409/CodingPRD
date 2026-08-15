"""Authentication / authorization helpers (PRD 2.1, validations priorities 1-4)."""
from flask import request

from errors import ApiError, unauthenticated, unauthorized_role, forbidden_ownership

ROLES = (
    "ConferenceServicesAdmin",
    "FacilitiesManager",
    "HousekeepingSupervisor",
    "FinanceOfficer",
    "ScreeningReviewer",
    "ClientCoordinator",
)

ADMIN = "ConferenceServicesAdmin"
FACILITIES = "FacilitiesManager"
HOUSEKEEPING = "HousekeepingSupervisor"
FINANCE = "FinanceOfficer"
SCREENING = "ScreeningReviewer"
COORDINATOR = "ClientCoordinator"

ALL_ROLES = list(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: header presence/validity, then endpoint role membership."""
    uid, role = authenticate()
    if role not in role_list:
        raise unauthorized_role()
    return uid, role


def check_group_ownership(uid, role, group_id):
    """Priority 4: a ClientCoordinator's X-User-ID must equal the target
    ConferenceGroup's id (directly or via the addressed resource's parent)."""
    if role == COORDINATOR and uid != group_id:
        raise forbidden_ownership()
