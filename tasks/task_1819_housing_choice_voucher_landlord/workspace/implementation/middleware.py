"""Auth header extraction and role checking (SCAFFOLD §1.4 p1-p2, §1.7; PRD §2.1)."""

from flask import request

import db
import errors

ROLES = {"HousingAuthorityAdmin", "Landlord", "Inspector"}
ENTITY_BACKED_ROLES = {"Landlord"}


def get_auth():
    """Extract and validate auth headers.

    Returns (role, user_id). Raises ERR_UNAUTHENTICATED on failure.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if not role or role not in ROLES:
        raise errors.unauthenticated()
    if role in ENTITY_BACKED_ROLES and not user_id:
        raise errors.unauthenticated()
    # For entity-backed Landlord role, the X-User-ID must reference an existing Landlord
    # record; otherwise ownership checks would be meaningless. We do not require the
    # landlord to exist here (existence checks run later per priority order), but we do
    # return the claimed id.
    return role, user_id


def require_roles(*allowed_roles):
    """Validate auth headers and that the role is permitted. Returns (role, user_id)."""
    role, user_id = get_auth()
    if role not in allowed_roles:
        raise errors.unauthorized()
    return role, user_id
