"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7).

Auth headers (authoritative per PRD §2.1):
  X-User-ID    -> opaque acting-user identifier
  X-User-Role  -> one of {SystemAdmin, CompoundingPharmacist,
                          QualityAssurancePharmacist, DispensingPharmacist}

Priority order (validations §1.4):
  1. auth header presence + known role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401)
  2. role permitted for the operation   -> ERR_INSUFFICIENT_PERMISSIONS (403)
"""
from flask import request

from errors import ApiError

KNOWN_ROLES = {
    "SystemAdmin",
    "CompoundingPharmacist",
    "QualityAssurancePharmacist",
    "DispensingPharmacist",
}


def get_user_context():
    """Return (user_id, role). Raises 401 when headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "Missing or invalid X-User-ID / X-User-Role header",
        )
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is in the allowed set; else 403."""
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not permitted for this operation" % role,
        )


# All four roles may read/list every resource.
ALL_ROLES = frozenset(KNOWN_ROLES)
