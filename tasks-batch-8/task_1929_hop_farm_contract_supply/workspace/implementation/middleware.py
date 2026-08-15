"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four declared roles
are FarmManager, LabTechnician, ContractManager, InsuranceAdjuster — all
opaque: X-User-ID is compared only against a stored filed_by_user_id on
insurance claims (segregation of duties), never against entity ids.
"""

from flask import request

from errors import unauthenticated, forbidden

ROLE_FARM_MANAGER = "FarmManager"
ROLE_LAB_TECHNICIAN = "LabTechnician"
ROLE_CONTRACT_MANAGER = "ContractManager"
ROLE_INSURANCE_ADJUSTER = "InsuranceAdjuster"

ROLES = {
    ROLE_FARM_MANAGER,
    ROLE_LAB_TECHNICIAN,
    ROLE_CONTRACT_MANAGER,
    ROLE_INSURANCE_ADJUSTER,
}

ALL_ROLES = [
    ROLE_FARM_MANAGER,
    ROLE_LAB_TECHNICIAN,
    ROLE_CONTRACT_MANAGER,
    ROLE_INSURANCE_ADJUSTER,
]


def authenticate():
    """Validate the two auth headers; return (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise unauthenticated()
    return role, user_id


def require_roles(allowed):
    role, user_id = authenticate()
    if role not in allowed:
        raise forbidden()
    return role, user_id
