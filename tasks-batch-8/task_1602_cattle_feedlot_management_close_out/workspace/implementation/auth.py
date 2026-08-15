"""Authentication / authorization (PRD 2.1)."""
from flask import request

from errors import raise_err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN_FOR_ROLE

ROLES = [
    "FeedyardManager",
    "FeedManager",
    "CattleHealthTech",
    "RiskManager",
    "ClaimsAdjuster",
    "ClaimsTreasurer",
    "BillingClerk",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip():
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "Missing or empty X-User-ID header")
    if not role or not role.strip():
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "Missing or empty X-User-Role header")
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE,
                  "Role %s is not authorized for this endpoint" % role)
