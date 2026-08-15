"""Auth header extraction and role checking (PRD section 2.1 / §2.6 stages 1-3)."""

from flask import request

import db
from errors import (
    ERR_FORBIDDEN,
    ERR_IDENTITY_NOT_QUALIFIED,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_error,
)

ALL_ROLES = (
    "OperationsManager",
    "EntrySupervisor",
    "Attendant",
    "RescueTeamLead",
    "SafetyOfficer",
    "BillingClerk",
)

# Entity-backed roles resolve X-User-ID to an ACTIVE Personnel row holding the
# required qualification (PRD section 2.1).
ROLE_REQUIRED_QUALIFICATION = {
    "EntrySupervisor": "ENTRY_SUPERVISOR",
    "Attendant": "ATTENDANT",
    "RescueTeamLead": "RESCUE_LEAD",
    "SafetyOfficer": "SAFETY_OFFICER",
}

OPAQUE_ROLES = ("OperationsManager", "BillingClerk")


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role, endpoint role membership, identity.

    Stage 1 (priority 1): both headers present and the role is one of the six
    declared roles, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    Stage 2 (priority 2): the declared role must be allowed on the endpoint,
    else ERR_FORBIDDEN (403).
    Stage 3 (priority 3): entity-backed roles resolve X-User-ID to an ACTIVE
    Personnel row holding the role's required qualification, else
    ERR_IDENTITY_NOT_QUALIFIED (403).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (not user_id or not role or not user_id.strip() or not role.strip()
            or role not in ALL_ROLES):
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and X-User-Role "
            "must be a declared role",
        )
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, "Role not permitted for this endpoint")
    person = None
    required = ROLE_REQUIRED_QUALIFICATION.get(role)
    if required is not None:
        person = db.personnel.get(user_id)
        if (person is None or person.get("status") != "ACTIVE"
                or required not in (person.get("role_qualifications") or [])):
            raise_error(
                ERR_IDENTITY_NOT_QUALIFIED,
                "X-User-ID does not resolve to an ACTIVE Personnel row holding "
                "the role's required qualification",
            )
    return user_id, role, person
