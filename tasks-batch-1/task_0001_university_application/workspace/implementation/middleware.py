"""Auth header extraction and role checking."""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ALLOWED_ROLES = {"Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"}
ANON_ROLE = "Anonymous"


def auth_required(allowed_roles, allow_anonymous: bool = False):
    """Decorator/helper. allowed_roles: iterable of role names that can call this endpoint.

    If allow_anonymous=True, the endpoint accepts a request without X-User-* headers.
    """
    allowed_set = set(allowed_roles)

    def _check():
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        if allow_anonymous and role is None and user_id is None:
            g.user_role = ANON_ROLE
            g.user_id = None
            if ANON_ROLE in allowed_set:
                return
            raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted")
        # Both headers must be present
        if not role or not user_id:
            raise APIError(ERR_UNAUTHENTICATED, 401, "Missing auth headers")
        # role must be in allowed enumeration (or Anonymous if endpoint allows it)
        if role not in ALLOWED_ROLES and role != ANON_ROLE:
            raise APIError(ERR_UNAUTHENTICATED, 401, "Invalid role")
        if role == ANON_ROLE and not allow_anonymous:
            raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted")
        g.user_role = role
        g.user_id = user_id
        if role not in allowed_set and not (role == ANON_ROLE and ANON_ROLE in allowed_set):
            raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
