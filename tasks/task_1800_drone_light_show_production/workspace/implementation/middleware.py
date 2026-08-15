"""Auth header extraction and role checking."""

from flask import request

import errors

ROLES = {"ProductionPlanner", "AuthorityOfficer", "SafetyOfficer", "FleetManager", "OpsAdmin"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise errors.unauthenticated()
    return uid, role


def require_role(*allowed):
    uid, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return uid, role
