"""Auth header extraction and RBAC checks (PRD §2.1 / SCAFFOLD validations).

Headers (PRD §2.1, authoritative):
  X-User-ID   — identifies the acting principal
  X-User-Role — declares the role: Operator | Guide | PartnerVenue | Guest | Anonymous

Auth precedence (PRD §2.9):
  1. ERR_UNAUTHENTICATED (401) when the header pair is missing on a protected
     endpoint.
  2. ERR_FORBIDDEN_ROLE (403) when present but the role is not permitted.
"""
from flask import request
import errors

VALID_ROLES = {"Operator", "Guide", "PartnerVenue", "Guest", "Anonymous"}


def get_identity():
    """Return (user_id, user_role) from the request headers (may be None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles):
    """Enforce authentication + RBAC for a protected endpoint.

    allowed_roles is the set/list of role names permitted on the operation
    (from PRD §4 / SCAFFOLD endpoint roles). Returns (user_id, user_role).

    Authentication: both X-User-ID and X-User-Role must be present and the role
    must be one of the five recognised values. A missing/invalid header pair on
    a protected endpoint -> ERR_UNAUTHENTICATED.

    Authorization: the role must appear in allowed_roles -> else ERR_FORBIDDEN_ROLE.
    """
    user_id, user_role = get_identity()

    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing or invalid X-User-ID / X-User-Role headers")

    if user_role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE,
                         "Role %s is not permitted for this operation" % user_role)

    return user_id, user_role


def resolve_reader(allowed_roles):
    """For GET endpoints that allow Anonymous.

    If valid auth headers are present, validate the role against allowed_roles
    (ERR_FORBIDDEN_ROLE if not permitted). If no headers are present and
    Anonymous is allowed, permit the read as Anonymous. If headers are partially
    present / invalid role, treat as unauthenticated only when Anonymous is not
    allowed; otherwise fall through to anonymous access.

    Returns (user_id, user_role).
    """
    user_id, user_role = get_identity()

    # Fully unauthenticated request.
    if not user_id and not user_role:
        if "Anonymous" in allowed_roles:
            return None, "Anonymous"
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing X-User-ID / X-User-Role headers")

    # Headers (at least partially) present.
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing or invalid X-User-ID / X-User-Role headers")

    if user_role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE,
                         "Role %s is not permitted for this operation" % user_role)

    return user_id, user_role
