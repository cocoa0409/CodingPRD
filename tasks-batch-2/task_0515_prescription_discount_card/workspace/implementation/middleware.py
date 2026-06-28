"""Auth header extraction and RBAC checks (PRD §2.1, §2.7; SCAFFOLD §1.4, §1.7)."""
from flask import request
import errors

VALID_ROLES = {"Anonymous", "Member", "PharmacyOperator", "CopayCardSponsor", "PlatformAdmin"}


def get_identity():
    """Return (user_id, role). May be (None, None) for unauthenticated requests."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles):
    """Enforce auth (priority 1) then role permission (priority 2).

    allowed_roles: iterable of role names permitted for this operation.
    Returns (user_id, role) on success. Raises ApiError otherwise.

    Note: 'Anonymous' in allowed_roles means the endpoint is public; auth headers
    are not required. If headers ARE supplied they still must be a known role
    is NOT required for public endpoints (public endpoints accept anybody).
    """
    user_id, role = get_identity()

    public = "Anonymous" in allowed_roles

    if public:
        # Public endpoint: no authentication required at all. Any caller (with or
        # without headers) is accepted. If a caller does present headers, we do
        # not reject on unknown role for public reads.
        return user_id, role

    # Protected endpoint: both headers required, role must be known (priority 1).
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()

    # Role permission (priority 2).
    if role not in allowed_roles:
        raise errors.forbidden_role()

    return user_id, role


def require_owner(user_id, role, owner_member_id):
    """Ownership check (priority 3) for entity-backed Member acting on owned resources.

    Only Member is entity-backed; the other operator roles are opaque and never
    compared against an entity id. PlatformAdmin etc. skip this check.
    """
    if role == "Member" and user_id != owner_member_id:
        raise errors.not_resource_owner()
