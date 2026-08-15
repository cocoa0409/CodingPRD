"""Auth middleware — PRD §2.1. Headers: X-User-ID and X-User-Role."""
from flask import request

import db
from errors import err_unauthenticated, err_forbidden

ROLES = [
    "TalentAssessmentAdmin",
    "HiringManager",
    "Interviewer",
    "Candidate",
    "DecisionOfficer",
    "ComplianceOfficer",
    "VendorRepresentative",
]

# entity-backed roles -> backing store
ENTITY_BACKED = {
    "Interviewer": "interviewers",
    "Candidate": "candidates",
    "VendorRepresentative": "vendors",
}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID / X-User-Role. Returns AuthContext. Raises 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthenticated("X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise err_unauthenticated("X-User-Role is not a declared role")
    if role in ENTITY_BACKED:
        store = db.stores[ENTITY_BACKED[role]]
        if user_id not in store:
            raise err_unauthenticated(
                "X-User-ID does not reference an existing instance of the backing entity"
            )
    return AuthContext(user_id, role)


def require_roles(ctx, allowed):
    if ctx.role not in allowed:
        raise err_forbidden()
