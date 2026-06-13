"""Auth header extraction and RBAC enforcement (PRD §2.1 / scaffold §1.7).

Auth headers (PRD §2.1): X-User-ID and X-User-Role. The system recognizes
exactly six roles: Applicant, VettingOfficer, EnrollmentOfficer, AppealsOfficer,
SchedulingAdmin, Auditor.

Validation order is fixed (PRD §2.9): auth headers (ERR_MISSING_AUTH_HEADERS)
first, then role authorization (ERR_FORBIDDEN_ROLE).
"""
from __future__ import annotations

from typing import Iterable, Optional

from flask import g, request

from errors import APIError, ERR_FORBIDDEN_ROLE, ERR_MISSING_AUTH_HEADERS

VALID_ROLES = {
    "Applicant",
    "VettingOfficer",
    "EnrollmentOfficer",
    "AppealsOfficer",
    "SchedulingAdmin",
    "Auditor",
}


def authenticate() -> None:
    """Validate the two auth headers. Populates g.user_role / g.user_id.

    Raises ERR_MISSING_AUTH_HEADERS (401) when either header is missing/blank or
    the role value is not one of the six recognized roles (malformed).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or not str(user_id).strip() or not str(role).strip():
        raise APIError(ERR_MISSING_AUTH_HEADERS, 401, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise APIError(ERR_MISSING_AUTH_HEADERS, 401, "Unrecognized X-User-Role value")
    g.user_role = role
    g.user_id = user_id


def authorize(allowed_roles: Iterable[str]) -> None:
    """Authorization check (ERR_FORBIDDEN_ROLE, 403) given the authenticated role."""
    role = getattr(g, "user_role", None)
    if role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this endpoint")


def require_auth(allowed_roles: Iterable[str]) -> None:
    """Auth (priority 1) then RBAC (priority 2), in that order."""
    authenticate()
    authorize(allowed_roles)


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
