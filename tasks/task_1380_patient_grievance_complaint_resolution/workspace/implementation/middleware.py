"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 p1/p2).

Seven roles are declared. Four are entity-backed: when X-User-Role is one of
PatientAdvocate / DepartmentInvestigator / QualityRiskOfficer /
PatientRelationsDirector, X-User-ID must reference an existing StaffMember whose
capabilities contain the mapped capability, or authorization fails with
ERR_UNAUTHORIZED_ROLE. SystemAdmin, IntakeCoordinator, and ComplianceAuditor
carry an opaque operator identifier not tied to any persisted entity.
"""

from flask import g, request

import db
import errors

ROLES = {
    "SystemAdmin",
    "IntakeCoordinator",
    "PatientAdvocate",
    "DepartmentInvestigator",
    "QualityRiskOfficer",
    "PatientRelationsDirector",
    "ComplianceAuditor",
}

# Every declared role may call any list or detail read (PRD §2.1)
ALL_ROLES = frozenset(ROLES)

# Entity-backed role -> required StaffMember capability
ROLE_CAPABILITY = {
    "PatientAdvocate": "ADVOCATE",
    "DepartmentInvestigator": "INVESTIGATOR",
    "QualityRiskOfficer": "QRO",
    "PatientRelationsDirector": "DIRECTOR",
}


def authenticate():
    """Validate X-User-ID / X-User-Role headers. Ladder rung 1."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_context()
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Role authorization + entity-backed capability check. Ladder rung 2."""
    if g.role not in roles:
        raise errors.unauthorized_role(
            f"Role {g.role} is not permitted for this endpoint"
        )
    capability = ROLE_CAPABILITY.get(g.role)
    if capability is not None:
        staff = db.staff_members.get(g.user_id)
        if staff is None or capability not in staff.get("capabilities", []):
            raise errors.unauthorized_role(
                f"Entity-backed role {g.role} requires a StaffMember with capability {capability}"
            )
