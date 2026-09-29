"""Actor identities and their request headers (PRD 2.1).

Four of the eight roles are entity-backed: for `FeedIntegrator`,
`Resident`, `ProviderAgent` and `PartnerAgent` the `X-User-ID` header is
the primary key of a persisted row, so those headers must be built from a
created entity's `id` rather than taken from a constant.  The remaining
four roles are opaque operator identities and may use the constants below.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identities (PRD 2.1).  These are never compared against an
# entity's id, so a fixed string is correct for them.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_USER_ID = "admin-user-a1"
MOVE_OPS_AGENT_USER_ID = "moveops-user-m1"
MOVE_OPS_AGENT_ALT_USER_ID = "moveops-user-m2"
COMPLIANCE_OFFICER_USER_ID = "compliance-user-c1"
COMPLIANCE_OFFICER_ALT_USER_ID = "compliance-user-c2"
EXTERNAL_GATEWAY_USER_ID = "gateway-user-g1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {
        "user_id": PLATFORM_ADMIN_USER_ID,
        "role": UserRole.PLATFORM_ADMIN.value,
    },
    "move_ops_agent": {
        "user_id": MOVE_OPS_AGENT_USER_ID,
        "role": UserRole.MOVE_OPS_AGENT.value,
    },
    "move_ops_agent_alt": {
        "user_id": MOVE_OPS_AGENT_ALT_USER_ID,
        "role": UserRole.MOVE_OPS_AGENT.value,
    },
    "compliance_officer": {
        "user_id": COMPLIANCE_OFFICER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "compliance_officer_alt": {
        "user_id": COMPLIANCE_OFFICER_ALT_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "external_service_gateway": {
        "user_id": EXTERNAL_GATEWAY_USER_ID,
        "role": UserRole.EXTERNAL_SERVICE_GATEWAY.value,
    },
    # Entity-backed roles are listed for completeness only.  Their user_id
    # placeholder resolves to no row, so use the make_*_headers builders
    # below with a real entity id whenever ownership matters.
    "feed_integrator": {
        "user_id": "feed-source-placeholder",
        "role": UserRole.FEED_INTEGRATOR.value,
    },
    "resident": {
        "user_id": "resident-placeholder",
        "role": UserRole.RESIDENT.value,
    },
    "provider_agent": {
        "user_id": "provider-placeholder",
        "role": UserRole.PROVIDER_AGENT.value,
    },
    "partner_agent": {
        "user_id": "partner-placeholder",
        "role": UserRole.PARTNER_AGENT.value,
    },
}


# ---------------------------------------------------------------------------
# Opaque-role header builders
# ---------------------------------------------------------------------------
def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a `PlatformAdmin`, whose id is an opaque operator string."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_move_ops_headers(user_id: str = MOVE_OPS_AGENT_USER_ID) -> Dict[str, str]:
    """Headers for a `MoveOpsAgent`, whose id is an opaque operator string."""
    return build_user_headers(user_id, UserRole.MOVE_OPS_AGENT.value)


def make_compliance_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> Dict[str, str]:
    """Headers for a `ComplianceOfficer`.

    The acting id is stamped as `reviewer_user_id` on a manual override and
    is later compared against the identifier submitting a postal filing, so
    tests that exercise segregation of duties must vary this argument.
    """
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_gateway_headers(user_id: str = EXTERNAL_GATEWAY_USER_ID) -> Dict[str, str]:
    """Headers for the `ExternalServiceGateway` inbound callback channel."""
    return build_user_headers(user_id, UserRole.EXTERNAL_SERVICE_GATEWAY.value)


# ---------------------------------------------------------------------------
# Entity-backed header builders.  The argument is the owning row's `id`.
# ---------------------------------------------------------------------------
def make_feed_integrator_headers(feed_source_id: str) -> Dict[str, str]:
    """Headers for a `FeedIntegrator`; the id is the acting FeedSource's id."""
    return build_user_headers(feed_source_id, UserRole.FEED_INTEGRATOR.value)


def make_resident_headers(resident_id: str) -> Dict[str, str]:
    """Headers for a `Resident`; the id is the acting Resident's id."""
    return build_user_headers(resident_id, UserRole.RESIDENT.value)


def make_provider_agent_headers(provider_id: str) -> Dict[str, str]:
    """Headers for a `ProviderAgent`; the id is the acting UtilityProvider's id."""
    return build_user_headers(provider_id, UserRole.PROVIDER_AGENT.value)


def make_partner_agent_headers(partner_id: str) -> Dict[str, str]:
    """Headers for a `PartnerAgent`; the id is the acting ReferralPartner's id."""
    return build_user_headers(partner_id, UserRole.PARTNER_AGENT.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for arbitrary header pairs, including undeclared roles."""
    return build_user_headers(user_id, role)
