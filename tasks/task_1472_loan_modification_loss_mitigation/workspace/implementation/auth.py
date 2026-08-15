"""Authentication / authorization / borrower-ownership (PRD 2.1, 2.7)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_BORROWER_OWNERSHIP

ROLES = [
    "ServicingAdmin",
    "Borrower",
    "LossMitAgent",
    "Underwriter",
    "AppealReviewer",
    "ServicingOps",
    "ForeclosureCounsel",
]

ALL_ROLES = list(ROLES)
NON_BORROWER_ROLES = [r for r in ROLES if r != "Borrower"]


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not authorized for this endpoint" % role)


def check_borrower_ownership(uid, loan):
    """Priority 5: Borrower-role caller owns the resource chain."""
    if loan is None or loan.get("borrower_id") != uid:
        raise_err(ERR_BORROWER_OWNERSHIP, "Borrower does not own the targeted resource chain")
