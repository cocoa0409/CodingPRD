"""Auth header extraction and role checking (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role. Exactly five roles are
recognized: BrandRep, ProductionPlanner, ProductionOperator, QAChemist,
QAManager.
"""
from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    raise_error,
)

ROLES = ("BrandRep", "ProductionPlanner", "ProductionOperator", "QAChemist", "QAManager")

# Read endpoints accept any of the five declared roles.
ANY_ROLE = ROLES


def get_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return user_id, role


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_context()
            if role not in roles:
                raise_error(ERR_FORBIDDEN_ROLE, "Role is not authorized for this operation")
            return fn(*args, user_id=user_id, role=role, **kwargs)

        return wrapper

    return decorator
