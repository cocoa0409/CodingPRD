"""Auth header extraction and role checking. Headers/roles from PRD §2.1."""
from flask import request

from errors import err

ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative", "MedicaidAgency"}


def get_identity():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/invalid.

    Authentication (priority 1) only checks the role header presence/validity.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: authorization. Raise ERR_FORBIDDEN if role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % role)
