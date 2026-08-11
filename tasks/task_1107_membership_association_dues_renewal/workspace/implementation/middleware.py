"""Auth header extraction and role checking — per SCAFFOLD validations[1,2] / PRD §2.1."""
from flask import request
import errors

ROLES = {"Member", "MembershipAdministrator", "DuesAdministrator"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    if not user_id:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate auth and require role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role


def require_owner_or_roles(member_id, *admin_roles):
    """For endpoints where Member may only act on self, or listed admin roles."""
    user_id, role = get_auth()
    if role == "Member":
        if user_id != member_id:
            raise errors.forbidden()
        return user_id, role
    if role in admin_roles:
        return user_id, role
    raise errors.forbidden()
