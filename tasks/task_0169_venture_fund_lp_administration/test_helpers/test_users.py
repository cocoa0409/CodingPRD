"""Pre-built role headers for every role in the PRD.

Three of the four roles (FundManager, FundAdministrator, ComplianceOfficer)
are opaque operators: their X-User-ID is never compared to any entity id, so
the shared constant is the canonical form. LimitedPartnerUser is entity-backed:
its X-User-ID must equal the acting LimitedPartner.id, so ownership-gated calls
MUST use make_limited_partner_headers(lp_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these directly; LimitedPartnerUser uses
# the shared constant only for non-ownership tests (e.g. 403-on-forbidden-role).
TEST_USERS = {
    "fund_manager_headers": build_user_headers("op-fund-manager-1", "FundManager"),
    "fund_administrator_headers": build_user_headers("op-fund-admin-1", "FundAdministrator"),
    "compliance_officer_headers": build_user_headers("op-compliance-1", "ComplianceOfficer"),
    # LimitedPartnerUser fallback: only valid where ownership is NOT exercised.
    "limited_partner_user_headers": build_user_headers("op-lp-user-1", "LimitedPartnerUser"),
}


def make_limited_partner_headers(lp_id: str) -> dict:
    """For LimitedPartnerUser (entity_backed:LimitedPartner). Pass the actual
    LimitedPartner.id as X-User-ID whenever the call is ownership-gated
    (statement reads, allocation funding)."""
    return build_user_headers(lp_id, "LimitedPartnerUser")


def fund_manager_headers() -> dict:
    return TEST_USERS["fund_manager_headers"]


def fund_administrator_headers() -> dict:
    return TEST_USERS["fund_administrator_headers"]


def compliance_officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]
