"""Auth context (PRD §2.1), RBAC gate (§2.8 priority 2), and per-request
mutation bookkeeping (PRD §2.4 version/updated_at bumps)."""

from flask import g, request

import db
from errors import ApiError

ROLES = {
    "AcquisitionsAnalyst",
    "UnderwritingCommittee",
    "DueDiligenceOfficer",
    "CapitalMarketsOfficer",
    "EscrowOfficer",
    "AssetManager",
    "PlatformAdmin",
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
    """Validation priority 2: role authorized for this endpoint, else
    ERR_INSUFFICIENT_PERMISSIONS (403)."""
    if g.user_role not in roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            f"Role {g.user_role} is not authorized for this endpoint",
            403,
        )
    return g.user_id


def bump(rec):
    """PRD §2.4: version increments by one on every mutation of the resource
    and updated_at refreshes. Guarded so each record bumps at most once per
    request — one logical mutation per request (e.g. PSA execute mutates the
    deal in several fields but increments deal.version exactly once)."""
    if rec is None or "version" not in rec:
        return
    key = id(rec)
    if key in g.bumped:
        return
    g.bumped.add(key)
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()
