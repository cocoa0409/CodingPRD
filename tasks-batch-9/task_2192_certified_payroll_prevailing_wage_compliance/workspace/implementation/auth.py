"""Authentication (rung 1), role authorization (rung 2), ownership (rung 5)
and staff capability (rung 6) per PRD 2.1 and 2.8."""

from flask import request

import db
from errors import ApiError

ROLES = (
    "PortalAdmin",
    "PayrollPreparer",
    "CertifyingOfficial",
    "AgencyComplianceOfficer",
    "LaborStandardsAuditor",
)

ALL_ROLES = list(ROLES)

ENTITY_BACKED = ("PayrollPreparer", "CertifyingOfficial")

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in ENTITY_BACKED


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not one of the five declared roles.")
    actor = Actor(str(user_id).strip(), role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return actor


def acting_staff(actor):
    """Resolve the acting ContractorStaff row for an entity-backed role."""
    staff = db.contractor_staff.get(actor.user_id)
    if staff is None:
        raise ApiError("ERR_STAFF_NOT_FOUND", "No contractor staff row with the acting X-User-ID.")
    return staff


def require_ownership(staff, contractor_id):
    """Rung 5."""
    if staff.get("contractor_id") != contractor_id:
        raise ApiError(
            "ERR_NOT_OWNER",
            "The acting staff member belongs to a different contractor.",
        )


PREPARE_CAPABILITIES = ("PREPARER", "BOTH")
CERTIFY_CAPABILITIES = ("CERTIFIER", "BOTH")


def require_capability(staff, allowed):
    """Rung 6."""
    if staff.get("capability") not in allowed:
        raise ApiError(
            "ERR_STAFF_CAPABILITY_MISSING",
            "The acting staff member's capability does not permit this operation.",
        )
