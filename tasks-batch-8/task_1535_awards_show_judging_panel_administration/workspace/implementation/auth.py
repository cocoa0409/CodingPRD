"""Authentication / authorization (PRD 2.1).

Headers: X-User-ID and X-User-Role, both present and non-empty, on every
endpoint except POST /awards/_clock/set_current_utc. Six recognized roles.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = [
    "ProgramAdmin",
    "Entrant",
    "Judge",
    "Auditor",
    "FulfillmentVendor",
    "Anonymous",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise_err(ERR_UNAUTHENTICATED,
                  "Missing or empty X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE,
                  "Role %s is not authorized for this endpoint" % role)


def forbid(msg="Ownership mismatch"):
    raise_err(ERR_FORBIDDEN_ROLE, msg)
