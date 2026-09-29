"""Authentication, role authorisation and Employee ownership (section 2.1, 2.8 ranks 1/2/4)."""

from functools import wraps

from flask import g, request

import db
from constants import ROLES
from errors import ApiError


def authenticate(allowed_roles):
    """Rank 1 (ERR_UNAUTHENTICATED) then rank 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role


def endpoint(*allowed_roles):
    """Decorator wiring the two access-control ranks onto a view function."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_employee():
    return getattr(g, "role", None) == "Employee"


def acting_user():
    return getattr(g, "user_id", None)


def require_employee_id(employee_id):
    """Rank 4: an Employee caller may only address their own employee record."""
    if is_employee() and employee_id != acting_user():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_owns_dependent(dependent):
    if dependent is not None:
        require_employee_id(dependent.get("employee_id"))


def require_owns_case(case):
    if case is not None:
        require_employee_id(case.get("employee_id"))


def soft_owner_check_dependent(dependent_id):
    """Body-reference ownership probe used before body-shape validation.

    Rank 4 sits above rank 5/6 in section 2.8, so when a body reference already
    resolves to somebody else's household the ownership failure is reported
    first. An unresolvable reference is left to rank 6.
    """
    if not is_employee():
        return
    dependent = db.get("dependents", dependent_id)
    if dependent is not None and dependent.get("employee_id") != acting_user():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def soft_owner_check_case(case_id):
    if not is_employee():
        return
    case = db.get("cases", case_id)
    if case is not None and case.get("employee_id") != acting_user():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
