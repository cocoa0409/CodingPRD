"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

import errors

# Recognized roles, spelled exactly (PRD §2.1).
KNOWN_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee", "Exhibitor", "Anonymous"}


def get_identity():
    """Read the X-User-ID / X-User-Role headers without enforcing presence.

    Returns (user_id, role) where either may be None when absent.
    """
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authenticate():
    """Enforce that X-User-ID and X-User-Role are present and the role is known.

    Returns (user_id, role) on success; raises ERR_UNAUTHENTICATED otherwise.
    Used by every endpoint except the two self-registration endpoints.
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Reject with ERR_FORBIDDEN when the role is not in the allowed set."""
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
