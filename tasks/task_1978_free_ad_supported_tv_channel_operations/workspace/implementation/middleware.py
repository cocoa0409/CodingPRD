"""Auth header extraction and role checking.

Headers: X-User-ID (identity), X-User-Role (role). For DistributorPartner,
X-User-ID is the id of the acting DistributorPlatform; for all other roles it
is an opaque operator identifier.
"""

from flask import request

from errors import raise_err, ERR_MISSING_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_CHANNEL_PROGRAMMER = "ChannelProgrammer"
ROLE_CONTENT_LICENSING = "ContentLicensing"
ROLE_AD_OPS = "AdOps"
ROLE_AD_QUALITY_REVIEWER = "AdQualityReviewer"
ROLE_FINANCE_ANALYST = "FinanceAnalyst"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_DISTRIBUTOR_PARTNER = "DistributorPartner"

ALL_ROLES = frozenset(
    [
        ROLE_PLATFORM_ADMIN,
        ROLE_CHANNEL_PROGRAMMER,
        ROLE_CONTENT_LICENSING,
        ROLE_AD_OPS,
        ROLE_AD_QUALITY_REVIEWER,
        ROLE_FINANCE_ANALYST,
        ROLE_FINANCE_CONTROLLER,
        ROLE_DISTRIBUTOR_PARTNER,
    ]
)


def caller():
    """Tier-1 auth check: both headers present and the role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise_err(
            ERR_MISSING_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return user_id, role


def require_roles(role, allowed):
    """Tier-3 role authorization check."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, "Caller role %s is not authorized for this endpoint" % role)


def body():
    """Request JSON body as a dict; malformed/missing bodies become {} so the
    required-field shape checks report them uniformly."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}
