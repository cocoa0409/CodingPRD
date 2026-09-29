"""Pre-built role headers for every role in the PRD.

`SponsorOperator` is the one entity-backed role: its `X-User-ID` must be the
acting Sponsor's own `id`, so ownership-gated calls always use
`make_sponsor_operator_headers(sponsor["id"])`. The other four roles carry an
opaque operator identifier that is never compared to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across the suite.
ADMIN_USER_ID = "pa-1"
MANAGER_USER_ID = "pm-1"
MANAGER_2_USER_ID = "pm-2"
COMPLIANCE_USER_ID = "co-1"
COMPLIANCE_2_USER_ID = "co-2"
BILLING_USER_ID = "bo-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "portfolio_manager_headers": build_user_headers(MANAGER_USER_ID, "PortfolioManager"),
    "portfolio_manager_2_headers": build_user_headers(
        MANAGER_2_USER_ID, "PortfolioManager"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        COMPLIANCE_2_USER_ID, "ComplianceOfficer"
    ),
    "billing_officer_headers": build_user_headers(BILLING_USER_ID, "BillingOfficer"),
    # Fallback only — never for an ownership-gated SponsorOperator call.
    "sponsor_operator_headers": build_user_headers("so-unowned", "SponsorOperator"),
}


def make_sponsor_operator_headers(sponsor_id: str) -> dict:
    """Headers for a SponsorOperator acting as the sponsor with this id.

    Pass the real Sponsor `id`: every mutating sponsor-scoped call compares the
    target resource's sponsor foreign key against this `X-User-ID`.
    """
    return build_user_headers(sponsor_id, "SponsorOperator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_portfolio_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PortfolioManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_billing_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingOfficer")
