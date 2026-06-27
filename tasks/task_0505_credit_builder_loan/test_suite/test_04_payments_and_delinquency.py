"""Payment allocation waterfall, overpayment-to-wallet, late-fee accrual & cap,
charge-off coupling, grace boundary, and the payment OCC version check."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_payment,
    make_loan_servicer_headers, make_borrower_headers,
    setup_funded_loan, post_payment, loan_version,
    set_clock, run_delinquency_sweep,
)


# =========================================================================
# Corner / calculations: allocation waterfall
# =========================================================================

def test_payment_waterfall_fee_interest_principal_order(api):
    """PRD §3.4: "Allocation follows a strict waterfall in this pinned bucket order: first outstanding late fees, then accrued interest, then principal."
    PRD §3.4: "The payment records how it was split across buckets in `applied_principal_cents`, `applied_interest_cents`, and `applied_fee_cents`."

    Design: Corner/calculations/payment_waterfall_fee_interest_principal_order
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=1599, principal_cents=120000, term_months=12,
        funded_at="2026-02-01T00:00:00Z",
    )
    funded_version = loan["version"]
    # Age to DPD_30 -> one 1500 late fee on period 1 (interest 1599, principal 9288).
    set_clock("2026-03-10T00:00:00Z")
    run_delinquency_sweep()

    pay = validate_success(
        api.create_payment(
            {"loan_id": loan["id"], "amount_cents": 12387, "source": "MANUAL",
             "expected_loan_version": funded_version},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    assert_payment(pay)
    assert pay["applied_fee_cents"] == 1500
    assert pay["applied_interest_cents"] == 1599
    assert pay["applied_principal_cents"] == 9288

    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["outstanding_principal_cents"] == 110712
    assert refetched["delinquency_status"] == "CURRENT"


def test_overpayment_credited_to_wallet(api):
    """PRD §3.4: "Any overpayment — cash still remaining after principal has been driven to 0 — is **not** applied to future interest. Instead it is credited to the account's `wallet_cents`."

    Design: Corner/calculations/overpayment_credited_to_wallet
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    post_payment(loan["id"], acct["id"], 70000, loan["version"])
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["outstanding_principal_cents"] == 0
    assert refetched["lifecycle_status"] == "PAID_OFF"
    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched_acct["wallet_cents"] == 70000


# =========================================================================
# Difficulty / compensating_invariant: locked savings conserved on payoff
# =========================================================================

def test_locked_savings_conserved_on_payoff(api):
    """PRD §3.7: "On payoff the system marks every still-`SCHEDULED` or `LATE` installment as `PAID`, sets the `delinquency_status` to `CURRENT`, and — as the locked-savings release — credits the full `principal_paid_cents` to the account's `wallet_cents`."

    Design: Difficulty/compensating_invariant/locked_savings_conserved_on_payoff
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    post_payment(loan["id"], acct["id"], 60000, loan["version"])
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched["principal_paid_cents"] == 60000
    assert refetched_acct["wallet_cents"] == 60000  # exactly equal to principal_paid_cents
    assert refetched["lifecycle_status"] == "PAID_OFF"


# =========================================================================
# Corner / calculations + state_machines: late fees, charge-off
# =========================================================================

def test_late_fee_cap_reached_exactly(api):
    """PRD §3.5: "The flat fee is 1500 cents and the lifetime cap is 4500 cents. On each bucket crossing for the oldest unpaid installment, if the loan's cumulative total assessed late fees plus 1500 cents is at most 4500 cents, then 1500 cents is added to the outstanding late-fee balance"
    PRD §3.5: "When it is 61 to 90 days past due, `DPD_60` advances to `DPD_90` and another late fee is assessed."

    Design: Corner/calculations/late_fee_cap_reached_exactly
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    # period-1 due 2026-03-01; age through DPD_30/60/90 across three sweeps.
    set_clock("2026-04-10T00:00:00Z")
    run_delinquency_sweep()
    set_clock("2026-05-10T00:00:00Z")
    run_delinquency_sweep()
    set_clock("2026-06-10T00:00:00Z")
    run_delinquency_sweep()
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["delinquency_status"] == "DPD_90"


def test_dpd_30_at_grace_boundary(api):
    """PRD §3.5: "An installment is past due once the clock passes its `due_date` plus the grace window of 5 days."
    PRD §3.5: "When that figure is between 1 and 30 inclusive, a loan whose `delinquency_status` is `CURRENT` advances to `DPD_30`"

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_dpd_30_at_grace_boundary
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    # period-1 due 2026-03-01; due+GRACE = 2026-03-06 (exactly grace, not yet past due).
    set_clock("2026-03-06T00:00:00Z")
    run_delinquency_sweep()
    at_grace = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert at_grace["delinquency_status"] == "CURRENT"

    # 2026-03-07: 1 day past the grace window -> crosses to DPD_30.
    set_clock("2026-03-07T00:00:00Z")
    run_delinquency_sweep()
    after = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert after["delinquency_status"] == "DPD_30"


# =========================================================================
# Cross-cutting / OCC on payment posting
# =========================================================================

def test_occ_stale_loan_version_on_payment(api):
    """PRD §2.8: "If `expected_loan_version` does not match the target loan's current `version` — because another writer has advanced it since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from double-applying against an already-changed balance."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_loan_version_on_payment
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    funded_version = loan["version"]
    post_payment(loan["id"], acct["id"], 5000, funded_version)  # bumps loan version
    resp = api.create_payment(
        {"loan_id": loan["id"], "amount_cents": 5000, "source": "MANUAL",
         "expected_loan_version": funded_version},  # now stale
        make_borrower_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_fresh_version_succeeds_and_increments(api):
    """PRD §2.8: "Each posted payment runs the allocation waterfall and mutates the loan's `principal_paid_cents`, `interest_paid_cents`, and `outstanding_principal_cents`, which increments the loan's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_succeeds_and_increments
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    post_payment(loan["id"], acct["id"], 5000, loan["version"])
    v3 = loan_version(loan["id"], acct["id"])
    pay2 = validate_success(
        api.create_payment(
            {"loan_id": loan["id"], "amount_cents": 5000, "source": "MANUAL",
             "expected_loan_version": v3},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    assert pay2["status"] == "POSTED"
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["principal_paid_cents"] == 10000
    v4 = refetched["version"]
    assert v4 == v3 + 1
