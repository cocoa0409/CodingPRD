"""Pre-built role headers for the four operator roles in the PRD (§2.1).

All four roles use opaque operator identifiers: `X-User-ID` is never compared
to any entity id — only to stored `created_by_user_id` / `prepared_by_user_id`
/ `approved_by_user_id` fields for segregation of duties (PRD §2.1, §2.7).
Segregation-of-duties tests therefore need headers for arbitrary user ids;
use the per-role builders below for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical caller for each role when the specific user id
# does not matter (no segregation-of-duties comparison on that call path).
TEST_USERS = {
    "fund_accountant_headers": build_user_headers("acct_default", "FundAccountant"),
    "fund_controller_headers": build_user_headers("ctl_default", "FundController"),
    "pricing_committee_headers": build_user_headers("pcs_default", "PricingCommittee"),
    "compliance_officer_headers": build_user_headers("comp_default", "ComplianceOfficer"),
}


def make_fund_accountant_headers(user_id: str) -> dict:
    """FundAccountant headers for a specific operator id."""
    return build_user_headers(user_id, "FundAccountant")


def make_fund_controller_headers(user_id: str) -> dict:
    """FundController headers for a specific operator id (SoD checks compare
    this id against the resource's stored preparer id)."""
    return build_user_headers(user_id, "FundController")


def make_pricing_committee_headers(user_id: str) -> dict:
    """PricingCommittee headers for a specific operator id."""
    return build_user_headers(user_id, "PricingCommittee")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers for a specific operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")
