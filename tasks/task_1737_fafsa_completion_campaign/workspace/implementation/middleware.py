"""Auth header extraction and role checking (scaffold §1.4 priorities 1-2, §1.7)."""

from flask import request

import errors

ROLES = {
    "CampaignAdmin",
    "SchoolCoordinator",
    "StaffMember",
    "Specialist",
    "MatchReviewer",
    "DataImporter",
}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_auth():
    """Priority 1: headers present, role declared. Returns AuthContext."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.raise_error(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return AuthContext(user_id=user_id, role=role)


def require_roles(auth, allowed):
    """Priority 2: acting role is in the endpoint's roles list."""
    if auth.role not in allowed:
        errors.raise_error(
            errors.ERR_UNAUTHORIZED_ROLE,
            f"Role {auth.role} is not authorized for this operation",
        )


def require_school_scope(auth, school_id):
    """Priority 2 (scope): SchoolCoordinator may only touch own school's resources."""
    if auth.role == "SchoolCoordinator" and auth.user_id != school_id:
        errors.raise_error(
            errors.ERR_SCHOOL_SCOPE_VIOLATION,
            "SchoolCoordinator may only act on resources of their own school",
        )


def require_ownership(auth, owner_id):
    """Priority 2 (ownership): StaffMember/Specialist acting on own assignments/cases."""
    if auth.user_id != owner_id:
        errors.raise_error(
            errors.ERR_OWNERSHIP_VIOLATION,
            "Caller may only act on their own assignments/cases",
        )
