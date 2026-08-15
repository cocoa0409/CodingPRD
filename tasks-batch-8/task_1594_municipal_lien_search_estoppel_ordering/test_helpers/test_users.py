"""Pre-built role headers for every role in the PRD.

All four roles have opaque identities (PRD 2.1): X-User-ID is an opaque
operator identifier, never an entity id. Ownership and segregation-of-duties
checks compare X-User-ID against recorded user ids, so tests that exercise
ownership or SoD must thread the same user id through every call — use the
make_*_headers builders with an explicit id for that.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe whenever the test does not depend on a specific
# caller identity (role-gating, malformed payloads, 404s, config writes).
TEST_USERS = {
    "title_agent_headers": build_user_headers("agent_1", "TitleAgent"),
    "title_agent_2_headers": build_user_headers("agent_2", "TitleAgent"),
    "research_analyst_headers": build_user_headers("analyst_1", "ResearchAnalyst"),
    "research_analyst_2_headers": build_user_headers("analyst_2", "ResearchAnalyst"),
    "qa_reviewer_headers": build_user_headers("qa_1", "QAReviewer"),
    "qa_reviewer_2_headers": build_user_headers("qa_2", "QAReviewer"),
    "provider_admin_headers": build_user_headers("admin_1", "ProviderAdmin"),
}

# A headers dict with no X-User-Role, for the missing-header rejection test.
HEADERS_WITHOUT_ROLE = {
    "X-User-ID": "admin_1",
    "Content-Type": "application/json",
}


def make_title_agent_headers(user_id: str) -> dict:
    """TitleAgent headers with a specific operator id (ownership checks compare
    this against the order's recorded title_agent_id)."""
    return build_user_headers(user_id, "TitleAgent")


def make_research_analyst_headers(user_id: str) -> dict:
    """ResearchAnalyst headers with a specific operator id (SoD compares this
    against research_completed_by_user_id and task completed_by_user_id)."""
    return build_user_headers(user_id, "ResearchAnalyst")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """QAReviewer headers with a specific operator id (SoD compares this
    against the discrepancy's filed_by_user_id and the order's researchers)."""
    return build_user_headers(user_id, "QAReviewer")


def make_provider_admin_headers(user_id: str = "admin_1") -> dict:
    """ProviderAdmin headers; owns the reference book and the logical clock."""
    return build_user_headers(user_id, "ProviderAdmin")
