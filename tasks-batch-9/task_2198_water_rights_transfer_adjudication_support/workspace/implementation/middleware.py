"""Authentication (priority 1), RBAC (priority 2) and Claimant ownership (priority 5)."""
from flask import request

from errors import ApiError

ROLE_CLAIMANT = "Claimant"
ROLE_ANALYST = "WaterRightsAnalyst"
ROLE_HEARING = "HearingOfficer"
ROLE_DECISION = "DecisionAuthority"
ROLE_ADJUDICATOR = "BasinAdjudicator"

ALL_ROLES = (
    ROLE_CLAIMANT,
    ROLE_ANALYST,
    ROLE_HEARING,
    ROLE_DECISION,
    ROLE_ADJUDICATOR,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_claimant(self):
        return self.role == ROLE_CLAIMANT


def authenticate(allowed_roles):
    """Priority 1 then priority 2. Returns a Caller."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both X-User-ID and X-User-Role headers are required.",
        )
    if role is None or not str(role).strip():
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both X-User-ID and X-User-Role headers are required.",
        )
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation." % role,
        )
    return Caller(str(user_id).strip(), role)


def require_owner(caller, owner_claimant_id):
    """Priority 5. Only the Claimant role is subject to the ownership test."""
    if caller.role != ROLE_CLAIMANT:
        return
    if owner_claimant_id is None or caller.user_id != owner_claimant_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "Claimant may only act on resources it owns.",
        )
