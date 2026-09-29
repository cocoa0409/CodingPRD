"""Authentication, role authorisation and ownership checks (PRD 2.1, 2.10 steps 1/2/6)."""
from flask import request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "LoyaltySupervisor",
    "LoyaltyAnalyst",
    "StoreOperator",
    "PumpTerminal",
    "SettlementClerk",
    "Member",
)

SITE_BACKED_ROLES = ("StoreOperator", "PumpTerminal", "SettlementClerk")
MEMBER_BACKED_ROLES = ("Member",)


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require(allowed_roles):
    """Step 1 (401) then step 2 (403)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognised role '%s'" % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return Ctx(user_id, role)


def own_member(ctx, member_id):
    """Step 6: role Member must act on its own member record."""
    if ctx.role in MEMBER_BACKED_ROLES and ctx.user_id != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this member resource")


def own_site(ctx, site_id):
    """Step 6: site-backed roles must act on their own site."""
    if ctx.role in SITE_BACKED_ROLES and ctx.user_id != site_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller does not own this site resource")
