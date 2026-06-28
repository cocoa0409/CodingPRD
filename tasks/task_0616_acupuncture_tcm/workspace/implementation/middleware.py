"""Auth header extraction and role checking (PRD 2.1).

Every request must carry two mandatory headers:
  X-User-ID   — identifies the acting user
  X-User-Role — declares the operational capacity

Recognized roles (spelled precisely): ClinicAdmin, Practitioner, Pharmacist,
Patient. Missing/malformed -> ERR_MISSING_AUTH. Authenticated but role not
permitted -> ERR_FORBIDDEN_ROLE.
"""

from flask import request

from errors import err

VALID_ROLES = {"ClinicAdmin", "Practitioner", "Pharmacist", "Patient"}


def get_auth():
    """Validate the two mandatory auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_AUTH", "Missing X-User-ID or X-User-Role header.")
    if user_id == "" or role == "":
        raise err("ERR_MISSING_AUTH", "Empty X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH", "Unrecognized X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2). ERR_FORBIDDEN_ROLE on failure."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
