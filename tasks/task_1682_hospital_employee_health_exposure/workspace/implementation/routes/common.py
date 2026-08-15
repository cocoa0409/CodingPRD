"""Shared route helpers."""
from db import store
from errors import ApiError


def get_or_404(collection, rid):
    ent = collection.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return ent


def staff_scope_check(role, user_id, employee_id):
    """StaffEmployee may act on / read only records belonging to their own id."""
    if role == "StaffEmployee" and user_id != employee_id:
        raise ApiError(
            "ERR_OWNERSHIP_REQUIRED",
            "StaffEmployee may access only their own records",
        )


def staff_scope_for_case(role, user_id, case):
    staff_scope_check(role, user_id, case["employee_id"])
