"""Auth / RBAC (PRD 2.1, validation priorities 1-3 and 7)."""
from flask import request

from errors import ApiError
from store import db

ROLES = ("PlatformAdmin", "CampaignAuthor", "ComplianceApprover", "Anonymous")
ENTITY_BACKED = ("CampaignAuthor", "ComplianceApprover")

ROLE_PERMITS = {
    "CampaignAuthor": ("CAMPAIGN_AUTHOR", "DUAL"),
    "ComplianceApprover": ("COMPLIANCE_APPROVER", "DUAL"),
}


class Ctx:
    def __init__(self, role, user_id, user):
        self.role = role
        self.user_id = user_id
        self.user = user  # AccountUser row, or None
        self.account_id = user["account_id"] if user else None

    @property
    def scoped(self):
        """True when tenant isolation applies to this caller."""
        return self.user is not None


def authorize(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # 1. Authentication of the headers.
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role != "Anonymous" and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")

    # 2. The claimed role is admitted by the operation.
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    # 3. For the entity-backed roles, the identifier resolves to an AccountUser
    #    whose user_role permits the claimed role.
    user = None
    if role in ENTITY_BACKED:
        user = db.account_users.get(user_id)
        if user is None or user["user_role"] not in ROLE_PERMITS[role]:
            raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")

    return Ctx(role, user_id, user)


def require_account(ctx, account_id):
    """7. Tenant isolation. PlatformAdmin and Anonymous are exempt."""
    if ctx.scoped and ctx.account_id != account_id:
        raise ApiError("ERR_CROSS_ACCOUNT_ACCESS")
