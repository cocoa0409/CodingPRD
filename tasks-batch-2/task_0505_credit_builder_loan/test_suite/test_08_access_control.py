"""Role-based access control: exclusive-operation denial, ownership, authentication."""
from prd_bench_local_runner.testing import build_user_headers

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    create_account, create_verified_account,
    setup_eligible_account_with_loan_disclosure, create_pending_loan,
)


def test_borrower_cannot_fund_loan(api):
    """PRD §2.1: "A `LoanServicer` performs onboarding, funding, servicing, graduation, card suspend/resume, and reporting reads."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/borrower_cannot_fund_loan
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"])
    resp = api.fund_loan(loan["id"], {}, make_borrower_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_loan_servicer_cannot_issue_disclosure(api):
    """PRD §2.1: "A `ComplianceOfficer` issues disclosures, freezes, unfreezes and closes accounts, and releases deposits."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/loan_servicer_cannot_issue_disclosure
    """
    acct = create_verified_account(state_code="CA")
    resp = api.create_disclosure(
        acct["id"], {"product_kind": "LOAN", "apr_bps": 0, "admin_fee_cents": 0},
        make_loan_servicer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_borrower_cannot_act_on_other_borrowers_loan(api):
    """PRD §2.1: "A `Borrower` who attempts to acknowledge a disclosure, post a deposit, activate a card, post a payment, request or execute a payoff, or cancel a loan that does not belong to them is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/borrower_cannot_act_on_other_borrowers_loan
    """
    acctA, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    acctB = create_account(state_code="CA")
    loan = create_pending_loan(acctA["id"], disc["id"])
    # Borrower whose X-User-ID is account B tries to cancel account A's loan.
    resp = api.cancel_loan(loan["id"], {}, make_borrower_headers(acctB["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    acct = create_account(state_code="CA")
    resp = api.get_account(acct["id"], build_user_headers("ghost-1", "Ghost"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
