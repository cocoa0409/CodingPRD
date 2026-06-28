"""Early-payoff quoting (dual variant), quote expiry, and the payoff release cascade."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_payoff_quote,
    make_loan_servicer_headers, make_borrower_headers,
    setup_funded_loan, post_payment, loan_version,
    set_clock,
)


# =========================================================================
# Difficulty / dual_variant_calc: payoff actual vs scheduled
# =========================================================================

def test_loan_payoff_actual_vs_scheduled(api):
    """PRD §3.8: "The **binding** figure, `payoff_amount_cents`, is the amount the borrower actually pays today: it is `outstanding_principal_cents`, plus accrued interest to date, plus the current outstanding late-fee balance."
    PRD §3.8: "The **comparison** figure, `scheduled_remaining_cents`, is the sum of `amount_due_cents` over every installment not yet `PAID` (those with status `SCHEDULED` or `LATE`)"
    PRD §3.8: "The borrower's benefit, `interest_savings_cents`, is `scheduled_remaining_cents` minus `payoff_amount_cents`."

    Design: Difficulty/dual_variant_calc/loan_payoff_actual_vs_scheduled
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=1599, principal_cents=120000, term_months=12,
        funded_at="2026-02-01T00:00:00Z",
    )
    # One on-time payment of 10887 against period 1 (interest 1599, principal 9288).
    post_payment(loan["id"], acct["id"], 10887, loan["version"])
    # Quote taken with clock still at funded_at -> per-diem since last due is 0.
    quote = validate_success(
        api.create_payoff_quote(loan["id"], {}, make_borrower_headers(acct["id"])),
        expected_status=201,
    )
    assert_payoff_quote(quote)
    assert quote["payoff_amount_cents"] == 110712
    assert quote["scheduled_remaining_cents"] == 119757
    assert quote["interest_savings_cents"] == 9045


# =========================================================================
# Corner / errors: quote expiry
# =========================================================================

def test_quote_expired_after_ttl(api):
    """PRD §3.8: "It is valid only when the cited quote's `status` is `ACTIVE`, the current clock is at or before `quote_as_of` plus 24 hours, and the loan's `lifecycle_status` is `ACTIVE`. If the quote is not `ACTIVE` or the clock is past the 24-hour window, the execution is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409)."

    Design: Corner/errors/quote_expired_after_ttl
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    quote = validate_success(
        api.create_payoff_quote(loan["id"], {}, make_borrower_headers(acct["id"])),
        expected_status=201,
    )
    # Advance two days, well past the 24-hour window.
    set_clock("2026-02-03T00:00:00Z")
    resp = api.early_payoff(loan["id"], {"quote_id": quote["id"]}, make_borrower_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)


# =========================================================================
# Difficulty / transitive_cascade: early-payoff release cascade
# =========================================================================

def test_early_payoff_release_cascade_depth3(api):
    """PRD §3.8: "On a valid execution the quote moves `ACTIVE → CONSUMED`, a synthetic payment for `payoff_amount_cents` is applied through the same allocation waterfall, and the loan is driven to `PAID_OFF`, releasing the locked savings to the wallet via the payoff cascade."
    PRD §3.7: "credits the full `principal_paid_cents` to the account's `wallet_cents`."

    Design: Difficulty/transitive_cascade/early_payoff_release_cascade_depth3
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    # Quote at funded_at (per-diem 0, apr 0) -> payoff_amount_cents == 60000.
    quote = validate_success(
        api.create_payoff_quote(loan["id"], {}, make_borrower_headers(acct["id"])),
        expected_status=201,
    )
    assert quote["payoff_amount_cents"] == 60000

    validate_success(api.early_payoff(loan["id"], {"quote_id": quote["id"]}, make_borrower_headers(acct["id"])))

    quotes, _meta = _list_quotes(api, loan["id"], acct["id"])
    consumed = next(q for q in quotes if q["id"] == quote["id"])
    assert consumed["status"] == "CONSUMED"

    refetched_loan = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched_loan["lifecycle_status"] == "PAID_OFF"
    assert refetched_loan["outstanding_principal_cents"] == 0

    refetched_acct = validate_success(api.get_account(acct["id"], make_loan_servicer_headers()))
    assert refetched_acct["wallet_cents"] == 60000


def _list_quotes(api, loan_id, account_id):
    from test_helpers import validate_paginated
    resp = api.list_payoff_quotes(loan_id, make_borrower_headers(account_id), params={"limit": 100})
    return validate_paginated(resp)
