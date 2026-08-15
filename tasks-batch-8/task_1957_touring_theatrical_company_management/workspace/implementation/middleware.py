"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 p1-2).

Every request must carry X-User-Role with one of the four declared role names;
X-User-ID is an opaque operator identifier, recorded for audit (submitted_by /
approved_by) and used by the segregation-of-duties checks — never compared to
entity ids.
"""

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = ("Producer", "TourManager", "CompanyManager", "Treasurer")


def authenticate():
    """Priority 1: X-User-Role present and a declared role -> else 401."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, 401,
                  "X-User-Role header is missing or not a recognized role")
    return request.headers.get("X-User-ID"), role


def require_roles(role, allowed):
    """Priority 2: declared role allowed for the endpoint/transition -> else 403."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, 403,
                  "Role %s is not authorized for this operation" % role)
