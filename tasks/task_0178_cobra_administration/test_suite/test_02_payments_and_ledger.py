"""Payment posting, the insignificant-shortfall threshold, paid_through_date
reconciliation, ledger conservation, refunds, and the OCC version guard.

Covers difficulty instances
paid_through_date_circular_order_payment_then_threshold,
deemed_full_payment_shortfall_equals_allowance,
refund_conserves_account_money_identity, and corner OCC / ledger instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    assert_payment, assert_account, assert_ledger_conservation, date_equals,
    create_payment_payload, refund_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

_ADMIN = TEST_USERS["plan_administrator_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_payment_shortfall_equal_to_allowance_is_deemed_full(api):
    """PRD §3.6: "The payment is deemed a full payment when the shortfall is at
    most the allowance — a shortfall exactly equal to the allowance still counts
    as fully paid."

    Design: Difficulty/boundary_precision_check/deemed_full_payment_shortfall_equals_allowance
    """
    # May owed 61200, allowance = max(5000, round_half_up(0.10*61200)) = 6120.
    # Payment 55080 -> shortfall 6120 == allowance -> deemed full.
    ctx = fx.setup_active_enrollment()
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    resp = api.create_payment(acct_id, create_payment_payload(55080, "2026-05"), _BILLING)
    pay = validate_success(resp, 201)
    assert_payment(pay)
    assert pay["deemed_full_payment"] is True, "shortfall == allowance must be deemed full"


def test_payment_shortfall_one_cent_over_allowance_not_deemed_full(api):
    """PRD §3.6: "The payment is deemed a full payment when the shortfall is at
    most the allowance — a shortfall exactly equal to the allowance still counts
    as fully paid."

    Design: Difficulty/boundary_precision_check/deemed_full_payment_shortfall_equals_allowance
    """
    # Payment 55079 -> shortfall 6121 > allowance 6120 -> NOT deemed full.
    ctx = fx.setup_active_enrollment()
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    resp = api.create_payment(acct_id, create_payment_payload(55079, "2026-05"), _BILLING)
    pay = validate_success(resp, 201)
    assert pay["deemed_full_payment"] is False, "shortfall > allowance must not be deemed full"


def test_deemed_full_payment_advances_paid_through_date(api):
    """PRD §3.6: "The system advances through the longest unbroken run of
    satisfied months starting at month 1 and sets paid_through_date to the last
    calendar day of the last month in that run; if month 1 is not satisfied,
    paid_through_date is null."
    PRD §3.6: "a month counts as satisfied when the sum of its POSTED payments
    plus the invoice's subsidy_applied_cents meets or exceeds the invoice's
    beneficiary_owed_cents, or when the latest payment for that month is a
    deemed-full payment."

    Design: Difficulty/combinatorial_formula/paid_through_date_circular_order_payment_then_threshold
    """
    ctx = fx.setup_active_enrollment()  # April paid -> paid_through 2026-04-30
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-05")
    api.create_payment(acct_id, create_payment_payload(55080, "2026-05"), _BILLING)  # deemed full
    acct = validate_success(api.get_account(acct_id, _BILLING))
    assert date_equals(acct["paid_through_date"], "2026-05-31"), (
        f"paid_through_date {acct['paid_through_date']}"
    )


def test_first_month_payment_sets_paid_through_to_end_of_month_1(api):
    """PRD §3.6: "If the enrollment is still PENDING_INITIAL_PREMIUM and a
    payment satisfies month 1 (payment-plus-subsidy meeting the month-1 amount
    owed, or a shortfall within the allowance) with received_date on or before
    the account's initial_premium_due_date, the enrollment bubbles from
    PENDING_INITIAL_PREMIUM to ACTIVE and the account's paid_through_date is
    recomputed to the last day of month 1."

    Design: Difficulty/combinatorial_formula/paid_through_date_circular_order_payment_then_threshold
    """
    ctx = fx.setup_elected_enrollment()  # PENDING, April invoice not yet created
    acct_id = ctx["account"]["id"]
    fx.create_invoice(acct_id, "2026-04")
    api.create_payment(acct_id, create_payment_payload(61200, "2026-04"), _BILLING)
    acct = validate_success(api.get_account(acct_id, _BILLING))
    assert date_equals(acct["paid_through_date"], "2026-04-30"), (
        f"paid_through_date {acct['paid_through_date']}"
    )


def test_refund_conserves_account_money_identity(api):
    """PRD §2.6: "the account's credit_balance_cents is computed as
    amount_paid_cents plus amount_subsidized_cents, minus amount_invoiced_cents,
    minus amount_refunded_cents, and this balance must never fall below zero."
    PRD §3.11: "A successful refund adds the refunded amount into
    amount_refunded_cents and recomputes credit_balance_cents, preserving the
    conservation identity of Section 2.6 (paid plus subsidized, less invoiced,
    less refunded)."

    Design: Difficulty/compensating_invariant/refund_conserves_account_money_identity
    """
    ctx = fx.setup_overpaid_account(payment_cents=70000)  # invoiced 61200, paid 70000 -> credit 8800
    acct_id = ctx["account"]["id"]
    version = ctx["account"]["version"]
    resp = api.refund(acct_id, refund_payload(8800, version), _BILLING)
    acct = validate_success(resp, 200)
    assert_account(acct)
    assert acct["credit_balance_cents"] == 0, f"credit {acct['credit_balance_cents']}"
    assert acct["amount_refunded_cents"] == 8800, f"refunded {acct['amount_refunded_cents']}"
    assert acct["amount_paid_cents"] == 70000, f"paid {acct['amount_paid_cents']}"
    assert acct["amount_invoiced_cents"] == 61200, f"invoiced {acct['amount_invoiced_cents']}"


def test_refund_preserves_identity_with_no_drift_after_overpay(api):
    """PRD §2.6: "This conservation identity (paid plus subsidized, less invoiced,
    less refunded) is the invariant that every billing operation preserves."

    Design: Difficulty/compensating_invariant/refund_conserves_account_money_identity
    """
    ctx = fx.setup_overpaid_account(payment_cents=70000)
    acct_id = ctx["account"]["id"]
    version = ctx["account"]["version"]
    resp = api.refund(acct_id, refund_payload(8800, version), _BILLING)
    acct = validate_success(resp, 200)
    # The conservation identity must hold exactly with no drift.
    assert_ledger_conservation(acct)


def test_get_account_ledger_matches_payments(api):
    """PRD §2.6: "amount_invoiced_cents is the sum of amount_due_cents across all
    of the account's invoices that are not in the VOID state; amount_paid_cents
    is the sum of amount_cents across all of the account's payments in the POSTED
    state".

    Design: Corner/endpoints/get_account_computed_ledger_matches_payments
    """
    ctx = fx.setup_active_enrollment(first_payment_cents=65000)  # invoice 61200, payment 65000
    acct_id = ctx["account"]["id"]
    acct = validate_success(api.get_account(acct_id, _ADMIN))
    assert acct["amount_invoiced_cents"] == 61200, f"invoiced {acct['amount_invoiced_cents']}"
    assert acct["amount_paid_cents"] == 65000, f"paid {acct['amount_paid_cents']}"
    assert acct["credit_balance_cents"] == 3800, f"credit {acct['credit_balance_cents']}"


def test_refund_with_zero_credit_balance_rejected(api):
    """PRD §3.11: "A refund requires a positive credit balance; against a zero
    balance it is rejected with ERR_NO_CREDIT_BALANCE."

    Design: Corner/validations/refund_with_zero_credit_returns_no_credit_balance
    """
    ctx = fx.setup_active_enrollment(first_payment_cents=61200)  # paid exactly -> credit 0
    acct_id = ctx["account"]["id"]
    version = fx.account_version(acct_id)
    resp = api.refund(acct_id, refund_payload(1000, version), _BILLING)
    validate_error(resp, "ERR_NO_CREDIT_BALANCE")


def test_refund_stale_account_version_rejected(api):
    """PRD §2.8: "If expected_account_version does not equal the account's
    current version — because a prior payment or a prior refund has already
    advanced the account since the client last read it, so the refund the client
    computed against its stale view no longer reflects the available credit — the
    request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/refund_stale_account_version_returns_412
    """
    ctx = fx.setup_overpaid_account(payment_cents=70000)  # credit 8800
    acct_id = ctx["account"]["id"]
    stale_version = fx.account_version(acct_id)
    # First refund advances version.
    fx.issue_refund(acct_id, 4000, stale_version)
    # Second refund reuses the now-stale version.
    resp = api.refund(acct_id, refund_payload(2000, stale_version), _BILLING)
    validate_error(resp, "ERR_STALE_VERSION")
    acct = validate_success(api.get_account(acct_id, _BILLING))
    assert acct["amount_refunded_cents"] == 4000, f"refunded {acct['amount_refunded_cents']}"


def test_refund_correct_version_succeeds_and_increments(api):
    """PRD §3.11: "The account's version is incremented by one."
    PRD §2.8: "the expected_account_version must match the account's current
    version, or the request is rejected with ERR_STALE_VERSION."

    Design: Corner/cross_cutting_complexity_layers/refund_correct_version_succeeds_and_increments
    """
    ctx = fx.setup_overpaid_account(payment_cents=70000)  # credit 8800
    acct_id = ctx["account"]["id"]
    version = fx.account_version(acct_id)
    resp = api.refund(acct_id, refund_payload(8800, version), _BILLING)
    acct = validate_success(resp, 200)
    assert acct["credit_balance_cents"] == 0, f"credit {acct['credit_balance_cents']}"
    assert acct["amount_refunded_cents"] == 8800, f"refunded {acct['amount_refunded_cents']}"
    assert acct["version"] == version + 1, f"version {acct['version']} should be {version + 1}"
