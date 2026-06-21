"""Auth header extraction and RBAC (PRD §2.1, §1.7)."""

from flask import request

import errors as E
from errors import fail

VALID_ROLES = {"ClinicAdmin", "Nurse", "Embryologist", "BillingSpecialist", "Patient"}


def get_auth():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        fail(E.ERR_MISSING_AUTH_CONTEXT, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        fail(E.ERR_MISSING_AUTH_CONTEXT, "Missing or malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is in the allowed set, else ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        fail(E.ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)


def get_body():
    """Parse JSON body, tolerating an empty/missing body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail(E.ERR_VALIDATION, "Request body is not valid JSON")
    if not isinstance(data, dict):
        fail(E.ERR_VALIDATION, "Request body must be a JSON object")
    return data
