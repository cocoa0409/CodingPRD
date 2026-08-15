"""Auth middleware and role checking."""
from flask import request
from errors import raise_err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_INSUFFICIENT_PERMISSIONS

ROLES = {
    "SourcingProgramAdmin",
    "AuditCoordinator",
    "Auditor",
    "SupplierContact",
    "ComplianceOfficer",
    "WorkerHotline",
}

ALL_BUSINESS_ROLES = {
    "SourcingProgramAdmin",
    "AuditCoordinator",
    "ComplianceOfficer",
    "Auditor",
    "SupplierContact",
}

PROGRAM_STAFF_ROLES = {"SourcingProgramAdmin", "AuditCoordinator", "ComplianceOfficer"}


def get_caller():
    """Extract and validate identity headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID header missing or invalid")
    if not role or role not in ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role header missing or invalid")
    return user_id, role


def require_roles(*allowed):
    """Check caller role is in allowed set; return (user_id, role)."""
    user_id, role = get_caller()
    if role not in allowed:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS,
                  f"Role {role} not permitted for this operation")
    return user_id, role


def get_pagination():
    """Parse limit/offset query params with defaults/clamps."""
    limit_arg = request.args.get("limit")
    offset_arg = request.args.get("offset")
    try:
        limit = int(limit_arg) if limit_arg is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_arg) if offset_arg is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
