"""Auth header extraction and role checks per PRD §2.1.

Headers: X-User-ID and X-User-Role. Six declared roles.
POST /api/permit-holders is exempt (Anonymous allowed without headers).
PermitHolder-role calls: X-User-ID is the PermitHolder id and must equal the
owning holder_id of the target/payload resource.
"""
from flask import request

from errors import err_unauthenticated, err_forbidden

ROLES = {
    "Anonymous",
    "PlatformAdmin",
    "CommunityAdmin",
    "Inspector",
    "EnforcementOfficer",
    "PermitHolder",
}


class Caller:
    def __init__(self, user_id, role, authenticated):
        self.user_id = user_id
        self.role = role
        self.authenticated = authenticated


def get_caller(allow_anonymous=False):
    """Stage-2 authentication. Returns a Caller.

    allow_anonymous: when True, missing headers produce an Anonymous caller
    instead of a 401 (permit-holder self-registration only).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        if allow_anonymous:
            return Caller(user_id or "", "Anonymous", False)
        raise err_unauthenticated()
    if role not in ROLES:
        raise err_unauthenticated()
    return Caller(user_id, role, True)


def require_role(caller, allowed_roles):
    """Stage-3 authorization: role permitted for the endpoint."""
    if caller.role not in allowed_roles:
        raise err_forbidden()


def check_holder_ownership(caller, *holder_ids):
    """Stage-3 ownership: PermitHolder calls must target their own resources."""
    if caller.role != "PermitHolder":
        return
    for hid in holder_ids:
        if hid is None:
            continue
        if caller.user_id != hid:
            raise err_forbidden("PermitHolder acting on a resource owned by another holder")


def check_holder_path_ownership(caller, path_holder_id):
    """For PermitHolder calls whose target is a PermitHolder itself."""
    if caller.role != "PermitHolder":
        return
    if caller.user_id != path_holder_id:
        raise err_forbidden("PermitHolder acting on a resource owned by another holder")
