"""Authentication and authorization (PRD 2.1, precedence band 1 of PRD 2.8)."""

from flask import request

from errors import fail

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

ROLES = (
    "POLICY_ADMIN",
    "VALIDATION_OFFICER",
    "VETTING_APPROVER",
    "ISSUANCE_OPERATOR",
    "REVOCATION_OFFICER",
    "COMPLIANCE_AUDITOR",
)

ALL_ROLES = ROLES


def authenticate(allowed_roles, require_user=True):
    """Band 1: missing user header, missing role header, unknown role, then
    role authorization."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if require_user and (user_id is None or str(user_id).strip() == ""):
        fail("ERR_MISSING_USER_HEADER", "The %s header is required." % USER_HEADER)
    if role is None or str(role).strip() == "":
        fail("ERR_MISSING_ROLE_HEADER", "The %s header is required." % ROLE_HEADER)
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return (user_id.strip() if isinstance(user_id, str) else user_id), role


def read_only(allowed_roles=ALL_ROLES):
    """GET endpoints: the role header is still mandatory, the user header is
    not (PRD 2.1)."""
    return authenticate(allowed_roles, require_user=False)


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body
