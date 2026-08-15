"""Auth header extraction + role gating (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Missing/empty headers or a
role outside the declared five -> ERR_UNAUTHENTICATED (401). Authenticated
but not permitted for the endpoint -> ERR_UNAUTHORIZED_ROLE (403).

Identity translation:
  - TrusteeAdmin / CaseManager / Auctioneer: opaque operator identifiers.
  - Beneficiary:      X-User-ID is the acting Beneficiary.id (entity-backed).
  - ThirdPartyBidder: X-User-ID is the acting BidderRegistration.id.
Entity-backed ownership checks run inside the route handlers once the target
entity has been loaded (they are priority 3, after role permission).
"""
from functools import wraps

from flask import request

from errors import err_unauthenticated, err_unauthorized_role

ALL_ROLES = (
    "TrusteeAdmin",
    "CaseManager",
    "Auctioneer",
    "Beneficiary",
    "ThirdPartyBidder",
)


def get_context():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED when missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise err_unauthenticated("X-User-ID header missing or empty")
    if role is None or str(role).strip() == "":
        raise err_unauthenticated("X-User-Role header missing or empty")
    if role not in ALL_ROLES:
        raise err_unauthenticated("unknown X-User-Role: " + str(role))
    return user_id, role


def require_roles(*roles):
    """Decorator: header presence/validity (priority 1) then role membership
    (priority 2)."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_context()
            if role not in allowed:
                raise err_unauthorized_role()
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator
