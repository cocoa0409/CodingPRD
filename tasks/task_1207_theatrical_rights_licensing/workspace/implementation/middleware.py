"""Auth header extraction and role checking per SCAFFOLD §1.4 / PRD §2.1."""
from flask import request

from errors import err_unauthenticated, err_unauthorized, err_forbidden_owner

ROLES = {"RightsAdmin", "LicensingOfficer", "Applicant", "MaterialsClerk", "FinanceOfficer"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED when missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Auth priorities 1 & 2: present headers, recognized role, role allowed on endpoint."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role


def check_applicant_owner(user_id, role, owning_organization_id):
    """Priority 3: entity-backed Applicant must act on own organization's resources."""
    if role == "Applicant" and user_id != owning_organization_id:
        raise err_forbidden_owner()
