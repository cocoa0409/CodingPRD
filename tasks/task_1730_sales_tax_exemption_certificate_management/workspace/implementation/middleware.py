"""Auth context (PRD §2.1) and per-request mutation bookkeeping (PRD §2.5)."""

from flask import g, request

import db
from errors import ApiError

ROLES = {
    "TenantAdmin",
    "ComplianceOfficer",
    "Auditor",
    "OrderClerk",
    "FulfillmentClerk",
    "BillingClerk",
}


def authenticate():
    """Validation priority 1: X-User-ID and X-User-Role headers present and
    well-formed, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not str(uid).strip() or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and must be well-formed",
            400,
        )
    g.user_id = uid
    g.user_role = role
    g.bumped = set()


def require_role(*roles):
    """Validation priority 2: role authorized for this endpoint."""
    if g.user_role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            f"Role {g.user_role} is not authorized for this endpoint",
            403,
        )


def bump(rec):
    """PRD §2.5: version increments by exactly one on every mutation of the
    resource and updated_at refreshes. Guarded so each record bumps at most
    once per request, matching the endpoint tables' 'increments version by 1'."""
    if rec is None or "version" not in rec:
        return
    key = rec["id"]
    if key in g.bumped:
        return
    g.bumped.add(key)
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()


def touch_updated_at(rec):
    """Refresh updated_at without a version increment (cert submit side effect
    on the tenant, PRD §3.3)."""
    rec["updated_at"] = db.now_iso()
