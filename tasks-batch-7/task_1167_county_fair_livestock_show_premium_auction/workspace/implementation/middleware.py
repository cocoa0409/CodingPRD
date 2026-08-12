"""Authentication and role/ownership helpers (PRD §2.1)."""
from flask import request

import errors

ROLES = {
    'FairBoardAdmin', 'Exhibitor', 'WeighMaster', 'ShowClerk', 'Judge',
    'Auctioneer', 'Buyer', 'HealthInspector', 'Treasurer',
}


def authenticate():
    """Validate the two identity headers; returns (user_id, role)."""
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Authenticate, then enforce endpoint role permission (ERR_FORBIDDEN)."""
    user_id, role = authenticate()
    if role not in roles:
        raise errors.forbidden()
    return user_id, role
