"""Authentication, RBAC and ownership guards (PRD §2.1, §2.9 steps 1-2 and 6)."""

from flask import request

from errors import fail

ROLE_BRAND_CHANNEL_MANAGER = "BrandChannelManager"
ROLE_BRAND_LEGAL_COUNSEL = "BrandLegalCounsel"
ROLE_MONITORING_ANALYST = "MonitoringAnalyst"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_RESELLER = "Reseller"
ROLE_DISTRIBUTOR = "Distributor"

ALL_ROLES = [
    ROLE_BRAND_CHANNEL_MANAGER,
    ROLE_BRAND_LEGAL_COUNSEL,
    ROLE_MONITORING_ANALYST,
    ROLE_PLATFORM_ADMIN,
    ROLE_RESELLER,
    ROLE_DISTRIBUTOR,
]

BRAND_STAFF = [
    ROLE_BRAND_CHANNEL_MANAGER,
    ROLE_BRAND_LEGAL_COUNSEL,
    ROLE_MONITORING_ANALYST,
    ROLE_PLATFORM_ADMIN,
]

STAFF_AND_RESELLER = BRAND_STAFF + [ROLE_RESELLER]
STAFF_AND_DISTRIBUTOR = BRAND_STAFF + [ROLE_DISTRIBUTOR]


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_reseller(self):
        return self.role == ROLE_RESELLER

    @property
    def is_distributor(self):
        return self.role == ROLE_DISTRIBUTOR


def authenticate(allowed_roles):
    """Step 1 (401) then step 2 (403)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header must name one of the six declared roles.")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not access this endpoint." % role)
    return Ctx(user_id, role)


def require_owner(ctx, row, reseller_field=None, distributor_field=None):
    """Step 6 — entity-backed roles act only on rows they own."""
    if ctx.is_reseller and reseller_field is not None:
        if row.get(reseller_field) != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "This row belongs to another reseller.")
    if ctx.is_distributor and distributor_field is not None:
        if row.get(distributor_field) != ctx.user_id:
            fail("ERR_NOT_RESOURCE_OWNER", "This row belongs to another distributor.")
    return row
