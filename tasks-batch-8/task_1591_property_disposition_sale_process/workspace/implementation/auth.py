"""Auth middleware: X-User-ID / X-User-Role headers (PRD section 2.1)."""
from flask import request

from errors import err_forbidden, err_unauthenticated

ROLES = (
    "DispositionManager",
    "AssetAnalyst",
    "InvestmentCommittee",
    "Broker",
    "Buyer",
    "ClosingOfficer",
    "LoanServicer",
)

ALL_ROLES = list(ROLES)


def auth():
    """Validate the two mandatory identity headers. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str):
        raise err_unauthenticated()
    if not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err_forbidden()
