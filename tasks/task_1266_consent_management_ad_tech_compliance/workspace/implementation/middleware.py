"""Auth header extraction and role/ownership checks (PRD §2.1, ladder rungs 1-2).

Every request must carry `X-User-ID` and `X-User-Role`. Recognized roles:
PrivacyAdmin, VendorManager, ComplianceAuditor, Visitor, Anonymous, Any.
"""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_FORBIDDEN_OWNERSHIP,
)

VALID_ROLES = (
    "PrivacyAdmin",
    "VendorManager",
    "ComplianceAuditor",
    "Visitor",
    "Anonymous",
    "Any",
)

# Roles allowed on `Any` (read) endpoints: every authenticated role.
# `Anonymous` is explicitly unauthenticated (PRD 2.1) and has no shared reads.
READ_ROLES = frozenset(r for r in VALID_ROLES if r != "Anonymous")


def get_context():
    """Extract and validate the user-context headers (ladder rung 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
            400,
        )
    return {"user_id": user_id, "role": role}


def require_role(*roles):
    """Ladder rung 2: the caller's role must be permitted the operation.

    `Any` means every authenticated role (all except Anonymous).
    Returns the request context on success.
    """
    ctx = get_context()
    if "Any" in roles:
        allowed = READ_ROLES
    else:
        allowed = set(roles)
    if ctx["role"] not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {ctx['role']} is not permitted to perform this operation",
            403,
        )
    return ctx


def require_visitor_ownership(visitor_id):
    """Ladder rung 2.5: a Visitor caller may only act on their own profile."""
    ctx = get_context()
    if ctx["role"] == "Visitor" and ctx["user_id"] != visitor_id:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP,
            "Visitor callers may only act on their own visitor profile",
            403,
        )
    return ctx
