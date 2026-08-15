"""Authentication / authorization middleware (PRD section 2.1, 2.8)."""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED, forbidden

ROLES = {
    "LessorAdmin",
    "LesseeRep",
    "TechInspector",
    "CreditOfficer",
    "LegalApprover",
    "FinanceManager",
}

ALL_ROLES = (
    "LessorAdmin",
    "LesseeRep",
    "TechInspector",
    "CreditOfficer",
    "LegalApprover",
    "FinanceManager",
)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-ID / X-User-Role headers",
            401,
        )
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                raise forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_lease_ownership(lease):
    """Entity-backed ownership: a LesseeRep may act only on leases whose
    lessee_id equals its X-User-ID."""
    if g.role == "LesseeRep" and lease["lessee_id"] != g.user_id:
        raise ApiError(
            ERR_FORBIDDEN, "LesseeRep may act only on leases its organization holds", 403
        )
