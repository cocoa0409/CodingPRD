"""Validation-priority conflict tests — when two checks fail at once, the
higher-priority validation wins per PRD §2.7.
"""
from test_helpers import (
    api_client, validate_error,
    set_clock, create_borrower, create_loan,
    make_borrower_headers,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


def test_invalid_state_wins_over_default_threshold(api):
    """Calling declare-default from IN_SCHOOL fails ERR_INVALID_STATE (state
    check, priority 6) — NOT ERR_DEFAULT_THRESHOLD_NOT_MET (business
    constraint, priority 9) — even though both checks would fail.

    PRD §2.7: "6. State preconditions of the requested transition
    (ERR_INVALID_STATE)."
    PRD §2.7: "9. Business constraints specific to a transition
    (ERR_DEFAULT_THRESHOLD_NOT_MET, ERR_REHABILITATION_NOT_QUALIFIED)."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_business_safety_default_threshold_wins_over_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Pri B", ssn_last4="0040")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    # Take the loan to IN_SCHOOL (not REPAYMENT).
    from test_helpers import api_client as ac
    from prd_bench_local_runner.testing import get_success_data
    get_success_data(ac.enter_school(loan["id"], LS))

    res = api.declare_default(loan["id"], CA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_unauthorized_wins_over_loan_not_found(api):
    """Borrower role calling /declare-default (CollectionsAgent-exclusive) on a
    non-existent loan returns ERR_UNAUTHORIZED (priority 2), not
    ERR_LOAN_NOT_FOUND (priority 3).

    PRD §2.7: "2. Role authorization under the operation's role matrix
    (ERR_UNAUTHORIZED)."
    PRD §2.7: "3. Existence of any path-referenced Loan (ERR_LOAN_NOT_FOUND)."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_vs_auth_loan_not_found_wins_over_unauthorized
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Auth B", ssn_last4="0041")
    res = api.declare_default(
        NON_EXISTENT_UUID, make_borrower_headers(borrower["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)
