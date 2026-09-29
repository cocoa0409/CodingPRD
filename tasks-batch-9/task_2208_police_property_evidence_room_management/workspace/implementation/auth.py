"""Authentication / RBAC (PRD 2.1) — validation stages 1 to 4."""

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "PropertyRoomManager",
    "EvidenceTechnician",
    "Investigator",
    "LabAnalyst",
    "CourtClerk",
    "InternalAuditor",
)

# entity-backed roles and the Custodian.role_type they require
ENTITY_BACKED = {
    "EvidenceTechnician": "EVIDENCE_TECH",
    "Investigator": "INVESTIGATOR",
    "LabAnalyst": "LAB_ANALYST",
    "InternalAuditor": "AUDITOR",
}

ALL_ROLES = list(ROLES)


class Principal(object):
    def __init__(self, user_id, role, custodian):
        self.user_id = user_id
        self.role = role
        self.custodian = custodian

    @property
    def custodian_id(self):
        return self.custodian["id"] if self.custodian else None


def authorize(allowed_roles):
    """Stages 1-4 of PRD 2.10 (the body-ownership half of stage 4 is applied by
    the two endpoints that carry those fields, immediately after this call)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_USER_CONTEXT")
    if role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    custodian = None
    if role in ENTITY_BACKED:
        custodian = db.custodians.get(user_id)
        if custodian is None or custodian["role_type"] != ENTITY_BACKED[role]:
            raise ApiError("ERR_CUSTODIAN_ROLE_MISMATCH")
    return Principal(user_id, role, custodian)


def require_self(principal, data, field):
    """Stage 4 body-ownership check: auditor_id / requested_by_custodian_id must
    equal X-User-ID when the caller is an entity-backed role and supplies it."""
    if principal.custodian is None:
        return
    value = data.get(field)
    if value is not None and value != principal.user_id:
        raise ApiError("ERR_CUSTODIAN_ROLE_MISMATCH")
