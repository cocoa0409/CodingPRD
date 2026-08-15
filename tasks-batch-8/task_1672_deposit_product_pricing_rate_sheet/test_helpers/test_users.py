"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles use opaque operator identifiers: `X-User-ID` is never compared
against an entity `id`, so shared constants are the canonical form. The
`make_*_headers` builders exist for flows where the user id itself matters
(exception segregation of duties records `submitted_by_user_id` /
`decided_by_user_id`).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "PricingAnalyst"),
    "committee_headers": build_user_headers("committee-1", "PricingCommittee"),
    "treasury_headers": build_user_headers("treasury-1", "TreasuryOfficer"),
    "banker_headers": build_user_headers("banker-1", "BranchBanker"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "channel_headers": build_user_headers("channel-1", "ChannelOperator"),
    "admin_headers": build_user_headers("admin-1", "OperationsAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PricingAnalyst")


def make_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PricingCommittee")


def make_treasury_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryOfficer")


def make_banker_headers(user_id: str) -> dict:
    """For BranchBanker. Pass a specific user id whenever segregation of duties
    on an exception request matters (the submitter cannot decide their own)."""
    return build_user_headers(user_id, "BranchBanker")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_channel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChannelOperator")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsAdmin")
