"""Authentication and RBAC (PRD 2.1)."""
from flask import request

import errors
from errors import fail

VALID_ROLES = {"TPAAdmin", "ClaimsExaminer", "FundManager", "Auditor"}


def require_auth(allowed_roles):
    """Gate 1 (401) then gate 2 (403). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        fail(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED, "Role %s is not permitted for this operation" % role)
    return user_id, role


# Every authenticated role may perform GET reads.
ANY_ROLE = VALID_ROLES
