"""Pre-built role headers for every role in the PRD (§2.1).

ServicingAdmin / LossMitAgent / Underwriter / AppealReviewer / ServicingOps /
ForeclosureCounsel use opaque operator identifiers: the shared constants below
are canonical. Borrower is entity-backed: any ownership-gated call MUST build
headers with the actual Borrower.id via make_borrower_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ServicingAdmin"),
    # Borrower is entity_backed: shared constant only for non-ownership tests.
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "agent_headers": build_user_headers("test-agent-1", "LossMitAgent"),
    "underwriter_headers": build_user_headers("uw_1", "Underwriter"),
    "reviewer_headers": build_user_headers("rev_1", "AppealReviewer"),
    "ops_headers": build_user_headers("test-ops-1", "ServicingOps"),
    "counsel_headers": build_user_headers("test-counsel-1", "ForeclosureCounsel"),
}


def make_borrower_headers(user_id: str) -> dict:
    """Borrower is entity_backed: X-User-ID must equal the Borrower.id for
    ownership-gated calls (applications, documents, plans, payments, appeals)."""
    return build_user_headers(user_id, "Borrower")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter is opaque; distinct ids matter for segregation-of-duties."""
    return build_user_headers(user_id, "Underwriter")


def make_appeal_reviewer_headers(user_id: str) -> dict:
    """AppealReviewer is opaque; the id is compared against the denying
    underwriter's id by the segregation-of-duties rule."""
    return build_user_headers(user_id, "AppealReviewer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ServicingAdmin")


def make_agent_headers(user_id: str = "test-agent-1") -> dict:
    return build_user_headers(user_id, "LossMitAgent")


def make_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "ServicingOps")


def make_counsel_headers(user_id: str = "test-counsel-1") -> dict:
    return build_user_headers(user_id, "ForeclosureCounsel")
