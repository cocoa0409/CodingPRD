"""Auth: X-User-ID / X-User-Role extraction, RBAC role gating."""
from functools import wraps

from flask import g, request

from errors import err_forbidden, err_unauthenticated

ROLES = {"FAAManager", "SponsorStaff", "ComplianceOfficer",
         "FinanceOfficer", "Auditor", "Contractor"}

ALL_ROLES = ("FAAManager", "SponsorStaff", "ComplianceOfficer",
             "FinanceOfficer", "Auditor", "Contractor")


def require(*roles):
    """Authenticate (401) then authorize the role set (403)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err_unauthenticated()
            if roles and role not in roles:
                raise err_forbidden(
                    f"Role {role} is not permitted to invoke this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
