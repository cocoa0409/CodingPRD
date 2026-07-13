"""The deposit gate, overpayment and quote-required guards, and money conservation across
a capture-then-refund cycle on the project ledger."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_payment_payload,
    setup_project_with_quote, new_project,
)


# --------------------------------------------------------------------------
# Difficulty/boundary_precision_check — deposit exactly at the 50% gate
# --------------------------------------------------------------------------
def test_deposit_exactly_50pct_accepted(api, salesrep_headers):
    """PRD §3.2: "When the payment's `kind` is `DEPOSIT`, it must bring the cumulative captured
    total to at least the required deposit — the deposit required is the project's
    `quoted_total_cents` multiplied by 50 percent, rounded half up — and a deposit that leaves
    the cumulative captured amount short of that figure is rejected with `ERR_DEPOSIT_TOO_LOW`
    (422)."
    PRD §3.2: "A payment is `CAPTURED` when recorded."

    A deposit of exactly 170000 (== round_half_up(340000 * 0.50)) meets the >= gate.

    Design: Difficulty/boundary_precision_check/deposit_exactly_50pct_accepted_ge_boundary
    """
    ctx = setup_project_with_quote()
    resp = api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=170000, kind="DEPOSIT"), salesrep_headers)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CAPTURED"


def test_deposit_exactly_50pct_sets_deposit_paid_status(api, salesrep_headers):
    """PRD §3.2: "The `amount_paid_cents` is the sum of `amount_cents` across payments whose
    `status` is `CAPTURED`; refunded payments are excluded."
    PRD §3.2: "otherwise it is `DEPOSIT_PAID` when `amount_paid_cents` is at least the required
    deposit (`quoted_total_cents` times 50 percent, rounded half up); otherwise it is `UNPAID`."

    Design: Difficulty/boundary_precision_check/deposit_exactly_50pct_accepted_ge_boundary
    """
    ctx = setup_project_with_quote()
    api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=170000, kind="DEPOSIT"), salesrep_headers)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["amount_paid_cents"] == 170000
    assert proj["payment_status"] == "DEPOSIT_PAID"


# --------------------------------------------------------------------------
# Corner/validations — deposit below gate, overpayment, quote required
# --------------------------------------------------------------------------
def test_deposit_below_50pct_returns_deposit_too_low(api, salesrep_headers):
    """PRD §3.2: "a deposit that leaves the cumulative captured amount short of that figure is
    rejected with `ERR_DEPOSIT_TOO_LOW` (422)."

    169999 is one cent below the 170000 required deposit.

    Design: Corner/validations/deposit_below_50pct_returns_deposit_too_low
    """
    ctx = setup_project_with_quote()
    resp = api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=169999, kind="DEPOSIT"), salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_TOO_LOW)


def test_balance_overpayment_returns_overpayment(api, salesrep_headers):
    """PRD §3.2: "no payment may push the total captured above the balance basis, which is the
    `final_invoice_cents` when one exists and otherwise the `quoted_total_cents`; a payment that
    would exceed that basis is rejected with `ERR_OVERPAYMENT` (422)."

    With no template, the basis is the quoted total 340000; 340001 exceeds it.

    Design: Corner/validations/balance_overpayment_returns_overpayment
    """
    ctx = setup_project_with_quote()
    resp = api.create_payment(
        ctx["p_id"], create_payment_payload(amount_cents=340001, kind="BALANCE"), salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


def test_payment_without_quote_returns_quote_required(api, salesrep_headers):
    """PRD §3.2: "There must be an `ACTIVE` quote to price against, or the payment is rejected
    with `ERR_QUOTE_REQUIRED` (409)."

    Design: Corner/validations/payment_without_quote_returns_quote_required
    """
    p = new_project(material_grade="PREMIUM")
    resp = api.create_payment(
        p["id"], create_payment_payload(amount_cents=1000, kind="DEPOSIT"), salesrep_headers)
    validate_error(resp, ApiErrorId.ERR_QUOTE_REQUIRED)


# --------------------------------------------------------------------------
# Difficulty/compensating_invariant — money conserved on capture-then-refund
# --------------------------------------------------------------------------
def test_refund_restores_amount_paid_to_zero(api, salesrep_headers):
    """PRD §3.2: "Refunding is permitted only while the payment's `status` is `CAPTURED`; the
    payment then moves to `REFUNDED` and the project's `amount_paid_cents`, `balance_due_cents`,
    and `payment_status` are recomputed so that money is conserved."
    PRD §3.2: "The `amount_paid_cents` is the sum of `amount_cents` across payments whose
    `status` is `CAPTURED`; refunded payments are excluded."

    Design: Difficulty/compensating_invariant/money_conserved_capture_then_refund
    """
    ctx = setup_project_with_quote()
    pay = validate_success(
        api.create_payment(ctx["p_id"], create_payment_payload(amount_cents=170000, kind="DEPOSIT"), salesrep_headers),
        expected_status=201,
    )
    refunded = validate_success(api.refund_payment(pay["id"], salesrep_headers))
    assert refunded["status"] == "REFUNDED"
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["amount_paid_cents"] == 0


def test_refund_restores_balance_and_unpaid_status(api, salesrep_headers):
    """PRD §3.2: "The `balance_due_cents` is the balance basis (the `final_invoice_cents` if
    present, else the `quoted_total_cents`) minus `amount_paid_cents`."
    PRD §3.2: "The `payment_status` is `PAID_IN_FULL` when `amount_paid_cents` is at least the
    balance basis; otherwise it is `DEPOSIT_PAID` when `amount_paid_cents` is at least the
    required deposit (`quoted_total_cents` times 50 percent, rounded half up); otherwise it is
    `UNPAID`."

    After refunding the only deposit, balance returns to the quoted total 340000 and status
    to UNPAID — the conserved quantity is money.

    Design: Difficulty/compensating_invariant/money_conserved_capture_then_refund
    """
    ctx = setup_project_with_quote()
    pay = validate_success(
        api.create_payment(ctx["p_id"], create_payment_payload(amount_cents=170000, kind="DEPOSIT"), salesrep_headers),
        expected_status=201,
    )
    api.refund_payment(pay["id"], salesrep_headers)
    proj = validate_success(api.get_project(ctx["p_id"], salesrep_headers))
    assert proj["balance_due_cents"] == 340000
    assert proj["payment_status"] == "UNPAID"
