"""Authentication, RBAC and respondent scoping (PRD 2.1, 2.9 priorities 1-3)."""

from flask import request

from errors import fail

ROLES = (
    "RespondentContact",
    "ComplianceAnalyst",
    "SanctionsOfficer",
    "FIGRelationshipManager",
    "CommitteeApprover",
    "PlatformAdmin",
)

OPERATOR_ROLES = (
    "PlatformAdmin",
    "SanctionsOfficer",
    "ComplianceAnalyst",
    "FIGRelationshipManager",
    "CommitteeApprover",
)

ALL_ROLES = OPERATOR_ROLES + ("RespondentContact",)


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_contact(self):
        return self.role == "RespondentContact"


def authenticate(allowed_roles):
    """Priority 1 then priority 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role name.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not use this endpoint." % role)
    return Ctx(user_id, role)


def scope(ctx, respondent_id):
    """Priority 3 — a RespondentContact may only address its own file."""
    if ctx.is_contact and respondent_id is not None and ctx.user_id != respondent_id:
        fail("ERR_RESPONDENT_SCOPE_VIOLATION",
             "This respondent contact may only address its own respondent record.")
