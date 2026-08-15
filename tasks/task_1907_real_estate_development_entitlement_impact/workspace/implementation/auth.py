"""Authentication (X-User-ID / X-User-Role) and per-endpoint RBAC.

Role values are spelled exactly: PlatformAdmin, Applicant, StaffReviewer,
DecisionAuthority. Gate 1 = authentication (401), gate 2 = authorization
(403); both run before any existence/state/business check.
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = ("PlatformAdmin", "Applicant", "StaffReviewer", "DecisionAuthority")


class Principal:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == "PlatformAdmin"

    @property
    def is_applicant(self) -> bool:
        return self.role == "Applicant"


def authenticate() -> Principal:
    """Gate 1: both headers present and the role is a declared value."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "X-User-ID and X-User-Role headers are required and the "
                       "role must be a declared role value", 401)
    return Principal(user_id, role)


def authorize(principal: Principal, allowed_roles) -> None:
    """Gate 2: the declared role must be authorized for this endpoint."""
    if principal.role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN,
                       f"Role {principal.role} is not permitted for this "
                       "operation", 403)


def require_owner(principal: Principal, project: dict) -> None:
    """Ownership gate: an Applicant acts only on its own applications.

    PlatformAdmin identity is opaque and never compared to entity ids.
    """
    if principal.role == "Applicant" and principal.user_id != project.get("applicant_id"):
        from errors import ERR_NOT_PROJECT_OWNER
        raise ApiError(ERR_NOT_PROJECT_OWNER,
                       "X-User-ID does not match the owning applicant_id of "
                       "the parent project", 403)
