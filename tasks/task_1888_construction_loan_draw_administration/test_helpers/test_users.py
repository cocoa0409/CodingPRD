"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. The borrower shared constant is a fallback for non-ownership tests
# only; borrower-role writes against a loan must use make_borrower_headers().
TEST_USERS = {
    "lender_admin_headers": build_user_headers("test-lender-admin-1", "LenderAdmin"),
    "draw_processor_headers": build_user_headers("test-draw-processor-1", "DrawProcessor"),
    "credit_officer_headers": build_user_headers("test-credit-officer-1", "CreditOfficer"),
    "loan_servicer_headers": build_user_headers("test-loan-servicer-1", "LoanServicer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
}


def make_borrower_headers(user_id: str) -> dict:
    """For Borrower (entity_backed:Borrower). Pass the actual Borrower.id as
    user_id whenever the call is ownership-gated (draws, line items, documents,
    retainage releases, conversion reviews)."""
    return build_user_headers(user_id, "Borrower")
