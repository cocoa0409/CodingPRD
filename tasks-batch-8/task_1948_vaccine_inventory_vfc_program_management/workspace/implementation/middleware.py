"""Auth middleware: X-User-ID / X-User-Role extraction and RBAC (PRD §2.1).

Validation order per PRD §2.12:
  1. user-context headers present and valid (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)
  2. role permitted for the endpoint        (ERR_INSUFFICIENT_PERMISSIONS, 403)
"""

from flask import request

from errors import missing_or_invalid_user_context, insufficient_permissions

ROLE_VACCINE_MANAGER = "VaccineManager"
ROLE_STATE_PROGRAM_OFFICER = "StateProgramOfficer"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"

VALID_ROLES = {ROLE_VACCINE_MANAGER, ROLE_STATE_PROGRAM_OFFICER, ROLE_COMPLIANCE_AUDITOR}

# Roles that may perform GET (read) operations — the "shared" set per §1.7
ALL_ROLES = [ROLE_VACCINE_MANAGER, ROLE_STATE_PROGRAM_OFFICER, ROLE_COMPLIANCE_AUDITOR]


def get_auth(allowed_roles):
    """Validate headers and role membership. Returns the user id or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")

    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise missing_or_invalid_user_context()
    if not user_role or not isinstance(user_role, str) or not user_role.strip():
        raise missing_or_invalid_user_context()
    # Syntactically valid role: must be one of the recognized role names.
    if user_role not in VALID_ROLES:
        raise missing_or_invalid_user_context()

    if user_role not in allowed_roles:
        raise insufficient_permissions()

    return user_id
