"""Pre-built role headers for every role in the PRD (§2.1).

FundTaxAdmin / TaxPreparer / TaxReviewer / InvestorServicesRep are opaque
operator roles: X-User-ID is not tied to any persisted entity. Investor is
entity-backed: X-User-ID must equal the acting Partner's id for
ownership-gated calls, so per-instance builders are mandatory there.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import PREPARER_USER_ID, REVIEWER_USER_ID

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400/404 paths, operator-only denials).
TEST_USERS = {
    "fund_tax_admin_headers": build_user_headers("admin_1", "FundTaxAdmin"),
    "tax_preparer_headers": build_user_headers(PREPARER_USER_ID, "TaxPreparer"),
    "tax_reviewer_headers": build_user_headers(REVIEWER_USER_ID, "TaxReviewer"),
    "investor_services_rep_headers": build_user_headers("rep_1", "InvestorServicesRep"),
    # Fallback only for non-ownership contexts; ownership-gated calls must use
    # make_investor_headers(partner["id"]).
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
}


def make_fund_tax_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "FundTaxAdmin")


def make_tax_preparer_headers(user_id: str = PREPARER_USER_ID) -> dict:
    """TaxPreparer headers with a specific X-User-ID (segregation-of-duties anchor)."""
    return build_user_headers(user_id, "TaxPreparer")


def make_tax_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    """TaxReviewer headers with a specific X-User-ID (segregation-of-duties anchor)."""
    return build_user_headers(user_id, "TaxReviewer")


def make_investor_services_rep_headers(user_id: str = "rep_1") -> dict:
    return build_user_headers(user_id, "InvestorServicesRep")


def make_investor_headers(user_id: str) -> dict:
    """Investor is entity-backed: pass the actual Partner.id as user_id whenever
    the call is ownership-gated (own record reads, K-1 acknowledge, ticket
    create/reopen)."""
    return build_user_headers(user_id, "Investor")
