"""Auth middleware: X-User-ID / X-User-Role extraction and RBAC (PRD 2.1)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN,
)

ROLES = {"QualityAssurance", "EnvironmentTech", "ProductionOperator", "MaterialHandler"}

QA = "QualityAssurance"
ET = "EnvironmentTech"
PO = "ProductionOperator"
MH = "MaterialHandler"
ALL_ROLES = [QA, ET, PO, MH]


def require_role(allowed_roles):
    """Validate the user-context headers and the endpoint's role set.

    Returns the acting user's X-User-ID (an opaque operator id).
    Priority 1: headers present and well-formed -> 400.
    Priority 2: role permitted for the endpoint  -> 403.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header value is not a recognized role",
        )
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return uid


def body():
    """Return the JSON request body as a dict ({} when absent/unparseable)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    return data
