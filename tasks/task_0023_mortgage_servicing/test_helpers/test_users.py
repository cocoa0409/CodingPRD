"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - `LoanServicer` identity is opaque: `X-User-ID` is an opaque operator
    identifier not compared to any entity row.
  - `ComplianceOfficer` identity is opaque: `X-User-ID` is the reviewer's
    operator identifier and is not compared to any entity row.
  - `Borrower` identity is entity-backed: `X-User-ID` must equal the
    `Borrower` row's `id`. Ownership checks on loan-scoped resources walk
    the FK chain back to a loan whose `borrower_id` equals `X-User-ID`.
    Use `make_borrower_headers(borrower_id)` for any ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not
# exercise ownership (e.g., 404-on-missing-resource, 400-on-bad-payload).
TEST_USERS = {
    "loan_servicer_headers": build_user_headers(
        "test-loan-servicer-1", "LoanServicer",
    ),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer",
    ),
    # Shared Borrower constant is a fallback for negative cases only;
    # ownership-gated calls MUST use make_borrower_headers(borrower_id).
    "borrower_headers": build_user_headers(
        "test-borrower-shared", "Borrower",
    ),
}


def make_loan_servicer_headers(opaque_id: str = "test-loan-servicer-1") -> dict:
    """LoanServicer is identity:opaque (PRD §2.1) — any string works."""
    return build_user_headers(opaque_id, "LoanServicer")


def make_compliance_officer_headers(
    opaque_id: str = "test-compliance-officer-1",
) -> dict:
    """ComplianceOfficer is identity:opaque (PRD §2.1) — any string works."""
    return build_user_headers(opaque_id, "ComplianceOfficer")


def make_borrower_headers(borrower_id: str) -> dict:
    """Borrower is identity:entity_backed (PRD §2.1).
    Pass the actual Borrower.id minted by POST /borrowers — ownership
    checks compare `X-User-ID` to `Loan.borrower_id` and to the FK chain
    on loan-scoped resources.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_anonymous_headers() -> dict:
    """No X-User-Role / X-User-ID — used to provoke ERR_UNAUTHENTICATED
    (PRD §2.1: missing either header is rejected)."""
    return {}
