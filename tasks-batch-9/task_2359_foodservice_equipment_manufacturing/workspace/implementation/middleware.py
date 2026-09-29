"""Authentication, RBAC and ownership-scope checks (PRD Section 2.1, checks 1-4)."""
from flask import request

from errors import ApiError

ROLES = (
    "ComplianceEngineer",
    "ListingReviewer",
    "ApplicationEngineer",
    "EngineeringApprover",
    "ChainAdmin",
    "ProductionPlanner",
    "ConnectedOpsEngineer",
    "ChannelManager",
    "ServicePartnerUser",
    "WarrantyAdjudicator",
    "PlatformAdmin",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_chain_admin(self):
        return self.role == "ChainAdmin"

    @property
    def is_partner_user(self):
        return self.role == "ServicePartnerUser"


def authorize(*allowed_roles):
    """Check 1 (authentication) then check 2 (role permission)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and a recognised X-User-Role are required")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "role %s may not call this operation" % role)
    return Actor(user_id, role)


def chain_scope(actor, owner_account_id):
    """Check 3. Skipped when the owning account cannot be resolved (a 404 follows)."""
    if actor.is_chain_admin and owner_account_id is not None and actor.user_id != owner_account_id:
        raise ApiError("ERR_CHAIN_SCOPE_VIOLATION", "resource belongs to another chain account")


def partner_scope(actor, owner_partner_id):
    """Check 4. Skipped when the owning partner cannot be resolved (a 404 follows)."""
    if actor.is_partner_user and owner_partner_id is not None and actor.user_id != owner_partner_id:
        raise ApiError("ERR_PARTNER_SCOPE_VIOLATION", "resource belongs to another service partner")
