"""Auth header extraction and RBAC (PRD §2.1).

Two mandatory headers: X-User-ID and X-User-Role. Recognized roles are exactly
ClinicAdmin, IntakeNurse, MedicalDirector, Nurse. Missing/blank either header,
or an unrecognized role -> ERR_UNAUTHENTICATED (401). Authenticated but role not
permitted for the endpoint -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"ClinicAdmin", "IntakeNurse", "MedicalDirector", "Nurse"}


def authenticate():
    """Validate the two auth headers. Returns (user_id, role) or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "Missing or blank X-User-ID header.")
    if role is None or role.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "Missing or blank X-User-Role header.")
    if role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown X-User-Role value: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if the authenticated role is not permitted."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s may not invoke this operation." % role)
