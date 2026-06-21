"""Pre-built role headers for every role in the PRD.

PRD §2.1: every request carries X-User-ID and X-User-Role. Three roles are
permitted: LoanServicer, Borrower, CollectionsAgent. The Borrower role is
entity-backed — X-User-ID must equal the acting Borrower entity's id.
LoanServicer and CollectionsAgent are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "loan_servicer_headers": build_user_headers("loan-servicer-1", "LoanServicer"),
    "collections_agent_headers": build_user_headers("collections-agent-1", "CollectionsAgent"),
    # entity_backed Borrower: shared constant is a fallback only for tests that
    # don't exercise ownership (e.g., bad-payload tests, unauth tests).
    "borrower_headers": build_user_headers("borrower-fallback", "Borrower"),
}


# Per-instance builder — REQUIRED for any ownership-gated Borrower call.
def make_borrower_headers(borrower_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the actual Borrower.id
    whenever the call is ownership-gated."""
    return build_user_headers(borrower_id, "Borrower")
