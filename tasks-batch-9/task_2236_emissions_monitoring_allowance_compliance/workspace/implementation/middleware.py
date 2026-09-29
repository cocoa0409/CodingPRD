"""Authentication, role authorization and facility scoping (PRD 2.1 / 2.8).

The auth band of the global precedence ladder is executed here, in order:

1. ``X-User-ID`` present and non-blank              -> ERR_UNAUTHENTICATED
2. ``X-User-Role`` present and a recognized role    -> ERR_UNAUTHENTICATED
3. role permitted on this endpoint                  -> ERR_UNAUTHORIZED
   (evaluated before any path id is resolved)
4. FacilityOperator scope                           -> ERR_FACILITY_SCOPE_VIOLATION
"""

from flask import request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE, ROLE_FACILITY_OPERATOR
from errors import fail

ANY_ROLE = ALL_ROLES


class Caller:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_facility_operator(self):
        return self.role == ROLE_FACILITY_OPERATOR


def authenticate(allowed_roles):
    """Steps 1-3 of the ladder."""
    user_id = request.headers.get(HEADER_USER_ID)
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or blank.")
    role = request.headers.get(HEADER_USER_ROLE)
    if role is None or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unrecognized.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return Caller(str(user_id), role)


def enforce_facility_scope(caller, facility):
    """Step 4. ``facility`` may be ``None`` when the path could not be resolved
    yet -- in that case the scope check is skipped and the later existence check
    produces the 404.
    """
    if facility is None:
        return
    if caller.role != ROLE_FACILITY_OPERATOR:
        return
    if facility.get("operator_org") != caller.user_id:
        fail(
            "ERR_FACILITY_SCOPE_VIOLATION",
            "FacilityOperator may only act on facilities it operates.",
        )
