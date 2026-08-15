"""Authentication / authorization helpers (PRD 2.1, validations priorities 1-3).

Identity binding by role (PRD 2.1):
- FacilityOwner / ContractorAdmin / StateRegulator: opaque X-User-ID; owner
  checks compare it against Facility.owner_account_id.
- Technician / ComplianceReviewer: X-User-ID is the id of a Technician
  resource.
- Any: read-only capacity shared by every authenticated caller on GETs.
"""
from flask import request

from errors import missing_context, insufficient_permissions, not_resource_owner

FACILITY_OWNER = "FacilityOwner"
CONTRACTOR_ADMIN = "ContractorAdmin"
TECHNICIAN = "Technician"
COMPLIANCE_REVIEWER = "ComplianceReviewer"
STATE_REGULATOR = "StateRegulator"
ANY = "Any"

KNOWN_ROLES = [
    FACILITY_OWNER, CONTRACTOR_ADMIN, TECHNICIAN, COMPLIANCE_REVIEWER,
    STATE_REGULATOR, ANY,
]

# Read-only endpoints authorize the "Any" capacity: every recognized role.
READ_ROLES = list(KNOWN_ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid == "" or role == "":
        raise missing_context()
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: header presence, then endpoint role membership."""
    uid, role = authenticate()
    if role not in role_list:
        raise insufficient_permissions()
    return uid, role


def check_facility_ownership(uid, facility):
    """Priority 3: owner-gated operations require X-User-ID == the parent
    Facility.owner_account_id."""
    if uid != facility["owner_account_id"]:
        raise not_resource_owner("X-User-ID does not match the facility's owner_account_id")
