"""Auth pipeline stages 1-3 (PRD 2.1, 2.7): headers, role membership, role-grade."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_ROLE_GRADE_MISMATCH,
)

ALL_ROLES = [
    "AuditAdmin",
    "ChiefAuditExecutive",
    "AuditCommittee",
    "AuditManager",
    "FieldAuditor",
    "QualityAssessor",
    "ManagementOwner",
]

# Entity-backed roles: X-User-ID is the acting Auditor's id (PRD 2.1).
ENTITY_BACKED_GRADES = {
    "AuditManager": {"MANAGER", "DIRECTOR"},
    "FieldAuditor": {"STAFF", "SENIOR", "MANAGER"},
    "QualityAssessor": {"MANAGER", "DIRECTOR"},
}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Stage 1: X-User-ID and X-User-Role present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise_error(ERR_UNAUTHENTICATED, "malformed auth headers")
    if user_id.strip() == "" or role.strip() == "":
        raise_error(ERR_UNAUTHENTICATED, "auth headers must be non-empty")
    return Caller(user_id.strip(), role.strip())


def check_role_allowed(caller: Caller, allowed_roles):
    """Stage 2: presented role must be in the endpoint's allowed set. A role value
    outside the seven recognized roles is in no endpoint's allowed set."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE, f"role {caller.role} is not allowed for this endpoint")


def check_role_grade(caller: Caller):
    """Stage 3: entity-backed roles resolve X-User-ID to an ACTIVE Auditor whose
    grade satisfies the role mapping (PRD 2.1)."""
    allowed_grades = ENTITY_BACKED_GRADES.get(caller.role)
    if allowed_grades is None:
        return  # opaque identity role
    auditor = db["auditors"].get(caller.user_id)
    if auditor is None:
        raise_error(ERR_ROLE_GRADE_MISMATCH,
                    f"no Auditor record for X-User-ID {caller.user_id}")
    if auditor["status"] != "ACTIVE":
        raise_error(ERR_ROLE_GRADE_MISMATCH, "auditor is not ACTIVE")
    if auditor["grade"] not in allowed_grades:
        raise_error(ERR_ROLE_GRADE_MISMATCH,
                    f"grade {auditor['grade']} does not satisfy role {caller.role}")


def authorized(allowed_roles) -> Caller:
    """Run auth stages 1-3 in the contractual order."""
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    check_role_grade(caller)
    return caller
