"""Auth header extraction and role checking (PRD §2.1)."""
from __future__ import annotations

from typing import Optional, Tuple

from flask import request

import errors

VALID_ROLES = {"Anonymous", "Filer", "StateAdmin", "ComplianceOfficer"}


def get_caller() -> Tuple[Optional[str], Optional[str]]:
    """Extract X-User-ID and X-User-Role from the current request.

    Returns (role, user_id). Either may be None if missing.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is not None and role == "":
        role = None
    if user_id is not None and user_id == "":
        user_id = None
    return role, user_id


def require_auth(allowed_roles: list) -> Tuple[str, str]:
    """Validate auth headers and role authorization.

    Returns (role, user_id) on success.
    Raises APIError on failure.
    """
    role, user_id = get_caller()
    # ERR_UNAUTHENTICATED: headers missing or role not recognized.
    if role is None or user_id is None or role not in VALID_ROLES:
        raise errors.err_unauthenticated()
    # ERR_UNAUTHORIZED: role recognized but not in the endpoint's allowed list.
    if role not in allowed_roles:
        raise errors.err_unauthorized()
    return role, user_id


def require_auth_optional_anonymous(allowed_roles: list) -> Tuple[Optional[str], Optional[str]]:
    """For endpoints where auth is optional (anonymous formation, clock set).

    If headers are absent entirely, returns (None, None). If headers are
    present, they must be valid and role must be in `allowed_roles`.

    For POST /business-entities specifically, the role list includes
    Anonymous + Filer; an unauthenticated caller is treated as Anonymous.
    """
    role, user_id = get_caller()
    if role is None and user_id is None:
        # Anonymous fallback
        if "Anonymous" in allowed_roles:
            return "Anonymous", None
        raise errors.err_unauthenticated()
    # If either header is present, both must be valid (per ERR_UNAUTHENTICATED
    # condition: "Missing or unrecognized X-User-Role / X-User-ID headers").
    if role is None or user_id is None or role not in VALID_ROLES:
        raise errors.err_unauthenticated()
    if role not in allowed_roles:
        raise errors.err_unauthorized()
    return role, user_id
