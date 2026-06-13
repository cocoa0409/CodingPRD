"""Auth header extraction + RBAC (PRD §2.1, §2.9).

Every request must carry X-User-ID and X-User-Role. The five recognized roles
are PlanAdministrator, PlanSponsor, BillingAgent, QualifiedBeneficiary, System.

Validation order is fixed (PRD §2.9): header well-formedness first, then role
permission, then existence, then ownership, then body shape, then state, then
business rules.
"""
from functools import wraps
from flask import request, g

from errors import ApiError

VALID_ROLES = {
    "PlanAdministrator",
    "PlanSponsor",
    "BillingAgent",
    "QualifiedBeneficiary",
    "System",
}


def require_auth():
    """Validate the user-context headers. Raises ERR_MISSING_OR_INVALID_USER_
    CONTEXT_HEADER if missing/malformed. Stores user id+role on flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-Role header missing or malformed")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(allowed_roles):
    """Decorator: validate headers then enforce role membership. The wrapped
    view runs only after both pass, so auth (400) always precedes forbidden
    (403) which precedes everything else."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_auth()
            if g.role not in allowed_roles:
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                               "Role %s is not permitted for this operation" % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
