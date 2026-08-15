"""Auth header extraction and role checking (PRD section 2.1).

Headers: X-User-ID and X-User-Role. Roles: ProgramAdmin, VolunteerLead,
Volunteer, Client, ReferralPartner. Missing headers or an unrecognized role
value is ERR_UNAUTHENTICATED (401); a recognized role not listed for the
endpoint is ERR_FORBIDDEN (403).
"""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = {"ProgramAdmin", "VolunteerLead", "Volunteer", "Client", "ReferralPartner"}


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if roles and role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN", 403,
                    f"Role {role} is not permitted for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
