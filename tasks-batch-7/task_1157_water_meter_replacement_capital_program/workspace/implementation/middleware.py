"""Auth header extraction and role checking (PRD 2.1 / 2.7 stages 1-2)."""
from functools import wraps

from flask import g, request

from errors import raise_err

# Six roles, spelled exactly as declared (PRD 2.1).
ROLES = (
    "ProgramManager",
    "Scheduler",
    "FieldContractor",
    "QualityAuditor",
    "AmiOperator",
    "CustomerService",
)
ALL_ROLES = ROLES


def require_roles(*allowed):
    """Stage 1 (authentication) then stage 2 (role authorization)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or not uid or role not in ROLES:
                raise_err("ERR_UNAUTHENTICATED",
                          "Missing or unknown X-User-Role / X-User-ID headers")
            if role not in allowed:
                raise_err("ERR_FORBIDDEN", "Role not permitted for this endpoint")
            g.user_role = role
            g.user_id = uid
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def check_contractor_ownership(resource_contractor_id):
    """Stage 3: FieldContractor's X-User-ID must equal the contractor id owning
    the targeted resource (PRD 2.1)."""
    if g.user_role == "FieldContractor" and g.user_id != resource_contractor_id:
        raise_err("ERR_CONTRACTOR_MISMATCH",
                  "FieldContractor does not own the targeted resource")
