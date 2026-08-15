"""Auth header extraction, role checking, and request parsing helpers."""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_VALIDATION

ROLES = {
    "ComplianceAdmin",
    "BusinessSponsor",
    "ScreeningAnalyst",
    "ComplianceOfficer",
    "FinanceReviewer",
    "AuditLead",
}

ALL_ROLES = sorted(ROLES)


def get_caller():
    """Extract and validate X-User-ID / X-User-Role headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(allowed):
    """Validate caller auth (priority 1) then role authorization (priority 2)."""
    user_id, role = get_caller()
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE, f"Role {role} is not authorized for this endpoint")
    return user_id, role


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset per §1.0 defaults (limit default 10, min 1, max 100, offset 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset
