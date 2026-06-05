"""Pre-built role headers for every role in the PRD (§2.1).

LoanOfficer, LoanServicer, and Auditor are opaque roles: X-User-ID is an opaque
operator identifier not compared to any entity id. Borrower is entity_backed:
its X-User-ID is the id of the acting Borrower entity, so ownership checks compare
the resource's borrower foreign key to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "loan_officer_headers": build_user_headers("officer-1", "LoanOfficer"),
    "loan_servicer_headers": build_user_headers("servicer-1", "LoanServicer"),
    # A second distinct servicer identity for segregation-of-duties tests.
    "loan_servicer_b_headers": build_user_headers("servicer-2", "LoanServicer"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Borrower is entity_backed; this shared constant is a fallback for non-ownership
    # tests only. Ownership-gated calls must use make_borrower_headers(borrower_id).
    "borrower_headers": build_user_headers("borrower-placeholder", "Borrower"),
}


def make_loan_officer_headers(user_id: str) -> dict:
    """LoanOfficer with a specific opaque X-User-ID. Used to control the activating
    officer's identifier for the later segregation-of-duties comparison."""
    return build_user_headers(user_id, "LoanOfficer")


def make_loan_servicer_headers(user_id: str) -> dict:
    """LoanServicer with a specific opaque X-User-ID (e.g. to differ from the activator)."""
    return build_user_headers(user_id, "LoanServicer")


def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the actual Borrower.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Borrower")
