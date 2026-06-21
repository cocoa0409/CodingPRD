"""Auth header extraction and RBAC enforcement (PRD §2.1)."""

from flask import request

from errors import err

VALID_ROLES = {"ArenaManager", "FrontDesk", "FieldMarshal", "LeagueDirector"}


def require_auth():
    """Validate the two mandatory headers (priority 1). Returns (user_id, role).

    Missing or malformed -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2). allowed is an iterable of role names."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  f"Role {role} is not permitted for this operation")


# Every authenticated role may read.
ALL_ROLES = VALID_ROLES
