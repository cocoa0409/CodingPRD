"""Pre-built role headers for every role in the PRD.

Both roles use an opaque identity (§2.1): X-User-ID is an operator identifier
not tied to any persisted entity. The only place the recorded identifier is
compared is the segregation-of-duties check on offer acceptance, so tests that
exercise that rule build headers with explicit, distinct user ids via
make_revenue_officer_headers / make_case_reviewer_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and tests not exercising the
# segregation-of-duties identity comparison.
TEST_USERS = {
    "revenue_officer_headers": build_user_headers("officer-1", "RevenueOfficer"),
    "case_reviewer_headers": build_user_headers("reviewer-1", "CaseReviewer"),
}


def make_revenue_officer_headers(user_id: str) -> dict:
    """RevenueOfficer headers with an explicit opaque operator id."""
    return build_user_headers(user_id, "RevenueOfficer")


def make_case_reviewer_headers(user_id: str) -> dict:
    """CaseReviewer headers with an explicit opaque operator id."""
    return build_user_headers(user_id, "CaseReviewer")
