"""Auth header extraction and RBAC (PRD Section 2.1).

Every request must carry X-User-ID and X-User-Role. Missing/malformed -> 401
ERR_MISSING_AUTH_HEADER. A present-but-unpermitted role -> 403
ERR_FORBIDDEN_FOR_ROLE.

Role check (priority 2) runs only after the auth header check (priority 1).
Existence (404), state (409), and business rules run only after both pass
(PRD Section 2.6: existence checking precedes state and business-rule eval;
validation priority order in scaffold Table 4).
"""
from errors import err

# The six roles spelled exactly as in PRD Section 2.1.
VALID_ROLES = {
    "Designer",
    "ChangeAdmin",
    "Approver",
    "QualityEngineer",
    "SupplierManager",
    "Viewer",
}


def extract_identity(headers):
    """Return (user_id, role) or raise ERR_MISSING_AUTH_HEADER.

    Both headers must be present and non-empty, and the role must be one of
    the six recognized roles (otherwise the role header is malformed).
    """
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_MISSING_AUTH_HEADER", "X-User-ID and X-User-Role headers are required")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH_HEADER", "X-User-Role is malformed")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_FOR_ROLE unless the caller's role is permitted."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Role %s is not permitted for this operation" % role)
