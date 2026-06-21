"""Auth header extraction and role checks (PRD §2.1).

Every authenticated request carries X-User-ID and X-User-Role. The four
recognized roles are PlatformAdmin, AccountOwner, ProfileUser, Anonymous.
The two invite-token endpoints (accept/decline) are the only operations that
require no authentication headers at all.

Identity binding (PRD §2.1):
  - AccountOwner: X-User-ID == acting Account.id
  - ProfileUser:  X-User-ID == acting Profile.id
  - PlatformAdmin / Anonymous: opaque, not tied to any persisted entity
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PlatformAdmin", "AccountOwner", "ProfileUser", "Anonymous"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Both headers must be present, non-empty, and the role must be one of the
    four recognized roles. A missing or malformed pair is rejected per
    validation priority 1.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Unknown role %r" % (role,))
    return user_id, role


def require_role(role: str, allowed: list):
    """Validation priority 2: acting role must be permitted for the operation."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %r not permitted for this operation" % (role,))
