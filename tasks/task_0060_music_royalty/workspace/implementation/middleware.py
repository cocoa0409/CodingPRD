"""Auth middleware: extract and validate X-User-Role / X-User-ID."""

from flask import request, g

from errors import raise_err

VALID_ROLES = {
    "PlatformAdmin",
    "RightsHolder",
    "RegistrationReviewer",
    "FinanceOps",
    "DisputeOfficer",
    "PlaybackSource",
}


def authenticate():
    """Run on every /royalty request: extract and validate headers."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise_err("ERR_AUTH_REQUIRED", "Missing X-User-Role or X-User-ID")
    if role not in VALID_ROLES:
        raise_err("ERR_AUTH_REQUIRED", f"Unknown role: {role}")
    g.role = role
    g.user_id = uid


def require_role(*allowed_roles):
    """Check role authorization. Raises ERR_FORBIDDEN if role not in allowed list."""
    if g.role not in allowed_roles:
        raise_err("ERR_FORBIDDEN", f"Role {g.role} not permitted")


def current_role() -> str:
    return g.role


def current_user_id() -> str:
    return g.user_id
