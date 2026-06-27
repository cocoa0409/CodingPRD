"""Loan lifecycle transitions: fund guards, cancel, graduation, terminal lockdown,
and the parallel lifecycle x delinquency axes."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_loan_servicer_headers, make_borrower_headers,
    setup_eligible_account_with_loan_disclosure, create_pending_loan, fund_loan,
    setup_funded_loan, setup_paid_off_loan, post_payment,
    setup_graduated_loan_with_active_card,
    set_clock, run_delinquency_sweep,
)


# =========================================================================
# Corner / state_machines: invalid transitions
# =========================================================================

def test_fund_already_active_loan_invalid_state(api):
    """PRD §3.3: "Funding is a `LoanServicer` action that drives the loan from `PENDING` to `ACTIVE`. It is valid only while the loan's `lifecycle_status` is `PENDING`"

    Design: Corner/state_machines/fund_already_active_loan_invalid_state
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"])
    fund_loan(loan["id"])
    resp = api.fund_loan(loan["id"], {}, make_loan_servicer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_active_loan_invalid_state(api):
    """PRD §3.3: "Cancellation is valid only while `lifecycle_status` is `PENDING`"

    Design: Corner/state_machines/cancel_active_loan_invalid_state
    """
    acct, disc = setup_eligible_account_with_loan_disclosure(state_code="CA", apr_bps=0)
    loan = create_pending_loan(acct["id"], disc["id"])
    fund_loan(loan["id"])
    resp = api.cancel_loan(loan["id"], {}, make_borrower_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =========================================================================
# Corner / state_machines: graduation
# =========================================================================

def test_graduate_active_not_paid_off_rejected(api):
    """PRD §3.6: "If any of these fails — the streak is below 6, the delinquency is not `CURRENT`, or principal remains outstanding so the loan is not yet `PAID_OFF` — the request is rejected with `ERR_GRADUATION_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/state_machines/graduate_active_not_paid_off_rejected
    """
    _acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    resp = api.graduate_loan(loan["id"], {}, make_loan_servicer_headers())
    validate_error(resp, ApiErrorId.ERR_GRADUATION_NOT_ELIGIBLE)


def test_graduate_paid_off_success_flags_card(api):
    """PRD §3.6: "On a successful graduation the loan moves `PAID_OFF → GRADUATED`; if a secured card exists for the same account and that card's `balance_cents` is 0, the card's `graduation_eligible` flag is set to true"

    Design: Corner/state_machines/graduate_paid_off_success_flags_card
    """
    acct, loan, card, _total = setup_graduated_loan_with_active_card(
        state_code="CA", principal_cents=60000, deposit_amounts=(50000,)
    )
    assert loan["lifecycle_status"] == "GRADUATED"
    refetched_card = validate_success(api.get_secured_card(card["id"], make_borrower_headers(acct["id"])))
    assert refetched_card["graduation_eligible"] is True


def test_terminal_graduated_loan_locked(api):
    """PRD §3.3: "GRADUATED, DEFAULTED, and CANCELLED are terminal."
    PRD §3.6: "Graduation is a `LoanServicer` action available on a loan whose `lifecycle_status` is `PAID_OFF`."

    Design: Corner/state_machines/terminal_graduated_loan_locked
    """
    # Build a PAID_OFF loan with streak >= 6 (lump of 60000 covers all 12), graduate it.
    acct, _disc, loan = setup_paid_off_loan(state_code="CA", principal_cents=60000)
    validate_success(api.graduate_loan(loan["id"], {}, make_loan_servicer_headers()))
    resp = api.graduate_loan(loan["id"], {}, make_loan_servicer_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =========================================================================
# Difficulty / non_linear_state_machine: parallel axes
# =========================================================================

def test_loan_parallel_axes_advance_and_cure(api):
    """PRD §3.5: "When that figure is between 1 and 30 inclusive, a loan whose `delinquency_status` is `CURRENT` advances to `DPD_30`"
    PRD §3.5: "When a posted payment clears all past-due installments — after allocation, no installment remains past its `due_date` plus the 5-day grace window — the delinquency axis cures back to `CURRENT`."
    PRD §3.5: "Active loans are unaffected by a freeze — they keep accruing" — the lifecycle
    axis stays ACTIVE while delinquency advances and cures independently.

    Design: Difficulty/non_linear_state_machine/loan_parallel_axes_independent
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=1599, principal_cents=120000, term_months=12,
        funded_at="2026-02-01T00:00:00Z",
    )
    funded_version = loan["version"]

    # Advance clock past period-1 due (2026-03-01) + grace; sweep -> DPD_30, ACTIVE.
    set_clock("2026-03-10T00:00:00Z")
    run_delinquency_sweep()
    aged = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert aged["lifecycle_status"] == "ACTIVE"
    assert aged["delinquency_status"] == "DPD_30"

    # A curing payment clears the past-due installment (fee 1500 + due 10887 = 12387).
    post_payment(loan["id"], acct["id"], 12387, funded_version)
    cured = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert cured["lifecycle_status"] == "ACTIVE"
    assert cured["delinquency_status"] == "CURRENT"
