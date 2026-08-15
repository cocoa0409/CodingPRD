"""Auth header extraction and RBAC (PRD Section 2.1).

Every request must carry X-User-ID and X-User-Role. Missing or empty ->
ERR_MISSING_AUTH_CONTEXT (400). A role not in the endpoint's role list ->
ERR_FORBIDDEN_ROLE (403).

Validation precedence (PRD Section 2.8): the auth-context check (1) runs
before role authorization (2), which runs before existence/state/business
checks.
"""
from errors import err

# The five roles spelled exactly as in PRD Section 2.1.
ALL_ROLES = [
    "JobberAdmin",
    "RetailerManager",
    "RouteDriver",
    "FieldAuditor",
    "JobberFinance",
]


def extract_identity(headers):
    """Return (user_id, role) or raise ERR_MISSING_AUTH_CONTEXT.

    Both headers must be present and non-empty.
    """
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role:
        raise err(
            "ERR_MISSING_AUTH_CONTEXT",
            "X-User-ID and X-User-Role headers are required",
        )
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE unless the caller's role is in allowed."""
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not permitted for this operation" % role,
        )
