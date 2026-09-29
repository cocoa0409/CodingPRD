"""Auth / RBAC middleware (validation ladder priorities 1-2, PRD §2.1)."""

import functools

from db import LOCK
from errors import ApiError
from flask import g, request

PLANT_ADMIN = "PlantAdmin"
PRODUCTION_PLANNER = "ProductionPlanner"
LINE_OPERATOR = "LineOperator"
QUALITY_INSPECTOR = "QualityInspector"
ENGINEERING_LEAD = "EngineeringLead"
WARRANTY_ANALYST = "WarrantyAnalyst"
SUPPLIER_PORTAL = "SupplierPortal"

INTERNAL_ROLES = [
    PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR,
    QUALITY_INSPECTOR, ENGINEERING_LEAD, WARRANTY_ANALYST,
]
ALL_ROLES = set(INTERNAL_ROLES) | {SUPPLIER_PORTAL}


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def endpoint(roles):
    """Wrap a view: serialise requests, then run ladder rules 1 and 2."""
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                user_id, role = authenticate(allowed)
                g.user_id = user_id
                g.role = role
                return fn(*args, **kwargs)
        return wrapper
    return decorator
