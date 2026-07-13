"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   - Contributor is entity_backed: this shared constant is a fallback for tests that
#     do NOT exercise ownership (e.g. 400/404 paths). Ownership-gated calls MUST use
#     make_contributor_headers(<contributor id>) instead.
#   - Reviewer, ComplianceOfficer, FinanceAdmin are opaque operator identities: the
#     shared constant is the canonical form.
TEST_USERS = {
    "contributor_headers": build_user_headers("test-contributor-1", "Contributor"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceAdmin"),
}


def make_contributor_headers(user_id: str) -> dict:
    """Headers for the Contributor role (entity_backed:Contributor). Pass the actual
    Contributor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Contributor")
