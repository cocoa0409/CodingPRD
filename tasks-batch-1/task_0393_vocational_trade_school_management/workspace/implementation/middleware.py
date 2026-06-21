"""Auth header extraction and role checking per PRD §2.1."""
from flask import request

from errors import err

ROLES = {"SystemAdmin", "Registrar", "FinancialAidOfficer", "AcademicAdvisor"}


def require_auth():
    """Validate presence/well-formedness of auth headers; return (user_id, role).

    Raises ERR_MISSING_AUTH_HEADER (401) when either header is missing or blank.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise err("ERR_MISSING_AUTH_HEADER", "Missing or malformed authentication headers.")
    return user_id, role


def require_role(allowed):
    """Auth (401) then authorization (403). Returns (user_id, role).

    `allowed` is an iterable of permitted role names.
    """
    user_id, role = require_auth()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role '%s' is not permitted for this operation." % role)
    return user_id, role


# Any authenticated role may perform reads.
ALL_ROLES = ["Registrar", "FinancialAidOfficer", "AcademicAdvisor", "SystemAdmin"]
