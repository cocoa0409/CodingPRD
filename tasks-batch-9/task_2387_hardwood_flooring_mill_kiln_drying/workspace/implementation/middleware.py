"""Authentication and role authorization (PRD section 2.1).

The acting user is carried in ``X-User-ID`` and the acting capacity in
``X-Role``; a request that omits ``X-Role`` but supplies ``X-User-Role`` is
treated as carrying that same role value, with ``X-Role`` taking precedence
when both are present.
"""

from functools import wraps

from flask import request

from errors import ApiError

MILL_ADMIN = "MillAdmin"
PROCUREMENT_CLERK = "ProcurementClerk"
KILN_OPERATOR = "KilnOperator"
MILL_SUPERVISOR = "MillSupervisor"
GRADE_INSPECTOR = "GradeInspector"
PREFINISH_SCHEDULER = "PrefinishScheduler"
BYPRODUCT_BROKER = "ByproductBroker"
WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"

ANONYMOUS = "Anonymous"

ALL_ROLES = (
    MILL_ADMIN,
    PROCUREMENT_CLERK,
    KILN_OPERATOR,
    MILL_SUPERVISOR,
    GRADE_INSPECTOR,
    PREFINISH_SCHEDULER,
    BYPRODUCT_BROKER,
    WARRANTY_ADJUDICATOR,
)


def acting_role():
    role = request.headers.get("X-Role")
    if role is None or role.strip() == "":
        role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        return None
    return role.strip()


def acting_user_id():
    value = request.headers.get("X-User-ID")
    if value is None or value.strip() == "":
        return None
    return value.strip()


def authorize(*roles):
    """Screening steps 1 and 2: authentication then role authorization."""
    permitted = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = acting_role()
            if role is None or role == ANONYMOUS:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in permitted:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
