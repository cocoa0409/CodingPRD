"""Auth header extraction and role checking (PRD 2.1)."""
from flask import request

from errors import err

# The system recognizes exactly four roles, spelled precisely (PRD 2.1).
VALID_ROLES = {"Anonymous", "Issuer", "Investor", "ComplianceOfficer"}


def get_auth():
    """Return (user_id, role) from X-User-ID / X-User-Role.

    Both headers must be present and well-formed; the role must be one of the
    four recognized roles. Otherwise reject with ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    return user_id, role


def get_auth_optional():
    """For public endpoints. Returns (user_id, role) when valid headers are
    present, else (None, None). If headers are present but malformed, still
    raise ERR_UNAUTHENTICATED so a bad declared role is not silently accepted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None and role is None:
        return None, None
    return get_auth()


def require_role(role, allowed):
    """Reject with ERR_FORBIDDEN_ROLE if role not permitted (PRD 2.1)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)
