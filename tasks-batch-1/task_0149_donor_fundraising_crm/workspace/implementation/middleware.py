"""Auth header extraction and role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Missing either -> 401.
Role not in the allowed set for the operation -> 403.
Identity is opaque for all three roles; X-User-ID is never matched to an entity.
"""

from flask import request

import errors

VALID_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if either header is
    missing or empty, or if the role is not one of the three recognized roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        # An unrecognized role cannot be authorized for anything; per §2.1 the
        # system recognizes exactly three roles. Treat unknown role as not
        # permitted (403) since the headers themselves are present.
        raise errors.unauthorized()
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED unless role is in the allowed collection."""
    if role not in allowed:
        raise errors.unauthorized()
