"""Auth header extraction, role checking, request parsing helpers."""
from flask import request

from errors import err

VALID_ROLES = {"ComplianceOfficer", "HrsaAuditor", "PharmacyOperator"}

# Internal-only fields that must never appear in serialized output.
_INTERNAL_FIELDS = {"_seq"}


def get_identity():
    """Return (user_id, user_role) after validating auth headers. PRD §2.1.

    A request missing either header, or carrying an unknown role, is
    ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, user_role


def require_role(user_role, allowed):
    """Enforce RBAC: ERR_FORBIDDEN_ROLE (403) when role is not permitted."""
    if user_role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint")


def get_json_body():
    """Parse a JSON request body, tolerating an empty/absent body as {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def serialize(record):
    """Strip internal fields from a record for output."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if k not in _INTERNAL_FIELDS}
