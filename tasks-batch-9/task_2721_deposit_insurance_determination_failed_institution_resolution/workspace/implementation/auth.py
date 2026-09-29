"""Authentication and role-based authorization (PRD sections 2.1 and 2.11).

Every request carries ``X-User-ID`` (the acting principal) and ``X-User-Role``
(the capacity it acts in).  Five roles are opaque operators; ``Bidder`` and
``Depositor`` are entity-backed, so their ``X-User-ID`` is the id of the
corresponding row.
"""

import functools

from flask import g, request

from errors import ApiError

CLOSING_MANAGER = "ClosingManager"
CLAIMS_AGENT = "ClaimsAgent"
CLAIMS_CERTIFIER = "ClaimsCertifier"
RESOLUTION_ANALYST = "ResolutionAnalyst"
RECEIVERSHIP_TRUSTEE = "ReceivershipTrustee"
BIDDER = "Bidder"
DEPOSITOR = "Depositor"

ALL_ROLES = (
    CLOSING_MANAGER,
    CLAIMS_AGENT,
    CLAIMS_CERTIFIER,
    RESOLUTION_ANALYST,
    RECEIVERSHIP_TRUSTEE,
    BIDDER,
    DEPOSITOR,
)

DECLARED_ROLES = set(ALL_ROLES)


def authenticate():
    """Stage 1 of PRD section 2.11."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require(*allowed_roles):
    """Bind an endpoint to the roles listed for it in PRD section 4."""
    permitted = set()
    for entry in allowed_roles:
        if isinstance(entry, (list, tuple, set, frozenset)):
            permitted.update(entry)
        else:
            permitted.add(entry)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in permitted:
                raise ApiError("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator
