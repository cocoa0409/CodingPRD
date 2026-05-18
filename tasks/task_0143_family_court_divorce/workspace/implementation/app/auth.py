"""Authentication and RBAC.

Per PRD §2.1, every request carries `X-User-ID` and `X-User-Role`. The role
must be one of six exact strings and the identity is interpreted per role.
"""
from flask import g, request

from app.errors import auth_missing, forbidden


ROLES = {
    "Petitioner",
    "Respondent",
    "AttorneyOfRecord",
    "Judge",
    "Mediator",
    "PlatformAdmin",
}


def authenticate():
    """Bind g.user_id and g.user_role; raise ERR_AUTH_MISSING on failure."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise auth_missing()
    role = role.strip()
    uid = uid.strip()
    if not role or not uid:
        raise auth_missing()
    if role not in ROLES:
        # Recognized auth header shape is wrong → still treat as missing/malformed
        # at priority 1 before any RBAC consideration.
        raise auth_missing("Unknown role value in X-User-Role")
    g.user_id = uid
    g.user_role = role


def require_roles(*allowed):
    """Raise ERR_FORBIDDEN if the current request's role is not in `allowed`."""
    if g.user_role not in allowed:
        raise forbidden(f"Role {g.user_role} is not permitted for this operation")


def role():
    return getattr(g, "user_role", None)


def user_id():
    return getattr(g, "user_id", None)
