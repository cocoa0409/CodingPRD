"""Auth header reader implementing validation-priorities 1, 2, 3 from §1.4.

Two headers are required: `X-User-ID` (opaque actor id, recorded into
audit-log rows as `actor_user_id`) and `X-User-Role` (one of the seven
concrete role names in the §1.7 matrix — `Any` is a synthetic label that
never appears in a real request and so is excluded from the recognised set).
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from flask import Response, g, request

from .constants import AUDIT_LOG_ALLOWLIST, ROLE_NAMES
from .envelope import error_envelope_response
from .errors import ApiError


def require_auth_headers() -> Optional[Response]:
    """Priority-1 and -2 auth check.

    Returns a Response when the headers are missing or unknown, else None.
    Stashes the actor id and role onto `g` for downstream handlers to read.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        return error_envelope_response(
            "ERR_MISSING_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    if user_role not in ROLE_NAMES:
        return error_envelope_response(
            "ERR_UNKNOWN_ROLE",
            f"Unknown role: {user_role!r}",
            403,
        )
    g.actor_user_id = user_id
    g.actor_role = user_role
    return None


def require_role(allowed: Iterable[str]) -> None:
    """Priority-3 permission check.

    Raises `ApiError("ERR_INSUFFICIENT_PERMISSIONS")` when the actor's role
    is not on the endpoint's allowlist.  The synthetic label `"Any"` in the
    allowlist means every authenticated role passes.
    """
    allowed_set = set(allowed)
    if "Any" in allowed_set:
        return
    role = getattr(g, "actor_role", None)
    if role is None or role not in allowed_set:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            f"Role {role!r} not on the endpoint's allowlist",
        )


def require_audit_log_allowlist() -> None:
    """The §2.1 audit-log specialisation.

    Three-role allowlist beyond the standard role check: AuditViewer,
    FestivalProducer, PlatformAdmin.  Raises ERR_AUDIT_LOG_FORBIDDEN
    when the actor is authenticated and has a known role but is not on
    the audit-log read allowlist.
    """
    role = getattr(g, "actor_role", None)
    if role is None or role not in AUDIT_LOG_ALLOWLIST:
        raise ApiError(
            "ERR_AUDIT_LOG_FORBIDDEN",
            "The audit log is restricted to AuditViewer, FestivalProducer, and "
            "PlatformAdmin roles",
        )


def actor_tuple() -> Tuple[str, str]:
    """Return the `(actor_user_id, actor_role)` pair for audit rows."""
    return getattr(g, "actor_user_id", "system"), getattr(g, "actor_role", "system")
