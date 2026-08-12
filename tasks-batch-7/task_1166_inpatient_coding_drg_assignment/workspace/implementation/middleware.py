"""Auth header extraction and role gating (PRD §2.1, validation ladder tiers 1-2)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = ("CodingManager", "Coder", "Auditor", "BillingClerk", "ComplianceOfficer")
ALL_ROLES = ROLES


def current_identity():
    """Returns (user_id, role); rejects with 401 when headers are missing/unknown."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not uid:
        raise ApiError(401, ERR_UNAUTHENTICATED,
                       "Missing or unknown X-User-Role, or missing X-User-ID")
    return uid, role


def require_roles(*roles):
    """Auth + endpoint-level role permission. Returns (user_id, role)."""
    uid, role = current_identity()
    if role not in roles:
        raise ApiError(403, ERR_FORBIDDEN,
                       f"Role {role} is not permitted for this endpoint")
    return uid, role
