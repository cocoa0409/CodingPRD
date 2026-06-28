"""Auth header extraction and RBAC (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four recognized roles
are exactly: Member, FrontDeskStaff, SalonManager, BillingSystem. Missing or
malformed -> ERR_MISSING_AUTH_HEADERS (401). Present but not permitted, or a
Member acting on a foreign member -> ERR_FORBIDDEN (403).
"""
from flask import request

import errors
from errors import err

VALID_ROLES = {"Member", "FrontDeskStaff", "SalonManager", "BillingSystem"}


def get_principal():
    """Return (user_id, role); raise ERR_MISSING_AUTH_HEADERS if absent/bad."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(errors.ERR_MISSING_AUTH_HEADERS, "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_AUTH_HEADERS, "X-User-Role header missing or malformed")
    return user_id.strip(), role


def require_role(role, allowed):
    """ERR_FORBIDDEN unless role is in the allowed set."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")


def require_self(role, user_id, member_id):
    """For Member-owned writes, X-User-ID must equal the path member id."""
    if role == "Member" and user_id != member_id:
        raise err(errors.ERR_FORBIDDEN, "Member may only act on its own membership")
