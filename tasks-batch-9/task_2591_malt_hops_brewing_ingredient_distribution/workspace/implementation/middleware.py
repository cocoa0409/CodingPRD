"""Authentication, role checking and brewer scoping.

Identity travels in two headers: ``X-User-ID`` and ``X-User-Role``.  For the
Brewer role the X-User-ID is the id of the Brewer entity itself; for every other
role it is an opaque actor id that is still recorded on segregation-of-duties
fields.
"""

from flask import request

from errors import ApiError

ROLES = (
    "Brewer",
    "AllocationManager",
    "CreditManager",
    "WarehouseOperator",
    "PlatformAdmin",
)

ALL_ROLES = ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_brewer(self):
        return self.role == "Brewer"


def authenticate():
    """Validation priority 1 then 2: headers present, then role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required",
        )
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE", "Unrecognised role '%s'" % role)
    return Actor(user_id, role)


def require(allowed_roles):
    """Priorities 1-3: authenticate then enforce the endpoint's role list."""
    actor = authenticate()
    if allowed_roles is not None and actor.role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation" % actor.role,
        )
    return actor


def scope_brewer(actor, brewer_id):
    """Priority 6: a Brewer actor may only address its own brewery's data."""
    if actor.is_brewer and brewer_id is not None and actor.user_id != brewer_id:
        raise ApiError(
            "ERR_BREWER_SCOPE_VIOLATION",
            "Brewer actor may only address resources owned by its own brewery",
        )
