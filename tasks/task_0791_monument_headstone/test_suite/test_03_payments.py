"""Payment ledger: parallel payment/production axes, zero-amount guard, signed amounts,
and balance sufficiency."""
import test_helpers as th


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / order_parallel_payment_vs_production
# ---------------------------------------------------------------------------
def test_deposit_advances_payment_axis_to_deposit_paid(api):
    """PRD §3.4: "A `DEPOSIT` payment advances the order's payment axis from `UNPAID` to
    `DEPOSIT_PAID`, but only if the cumulative captured `amount_paid_cents` after the payment
    reaches at least `deposit_amount_cents`; a deposit that leaves the paid amount short of the
    deposit is rejected with `ERR_DEPOSIT_NOT_PAID`."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_vs_production
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": True, "permit_fee_cents": 12000})
    th.validate_success(
        api.create_payment(th.create_payment_payload(ctx["order"]["id"], "DEPOSIT", 33880),
                           ctx["customer_headers"]), 201,
    )
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["payment_status"] == "DEPOSIT_PAID", order


def test_deposit_leaves_production_axis_in_drafting(api):
    """PRD §3.4: "The payment axis is independent of production: it runs `UNPAID → DEPOSIT_PAID →
    PAID_IN_FULL`, with `REFUNDED` reachable only through cancellation."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_vs_production
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": True, "permit_fee_cents": 12000})
    th.validate_success(
        api.create_payment(th.create_payment_payload(ctx["order"]["id"], "DEPOSIT", 33880),
                           ctx["customer_headers"]), 201,
    )
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["production_status"] == "DRAFTING", order


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / zero_payment_amount_edge
# ---------------------------------------------------------------------------
def test_zero_amount_deposit_rejected(api):
    """PRD §3.4: "For any `DEPOSIT` or `BALANCE`, the `amount_cents` must be strictly greater than
    zero, or the request is rejected with `ERR_ZERO_PAYMENT_AMOUNT`."

    Design: Difficulty/boundary_precision_check/zero_payment_amount_edge
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": True, "permit_fee_cents": 12000})
    resp = api.create_payment(
        th.create_payment_payload(ctx["order"]["id"], "DEPOSIT", 0), ctx["customer_headers"]
    )
    th.validate_error(resp, th.ApiErrorId.ERR_ZERO_PAYMENT_AMOUNT.value)


def test_zero_amount_deposit_leaves_order_unpaid(api):
    """PRD §3.4: "For any `DEPOSIT` or `BALANCE`, the `amount_cents` must be strictly greater than
    zero, or the request is rejected with `ERR_ZERO_PAYMENT_AMOUNT`."

    Design: Difficulty/boundary_precision_check/zero_payment_amount_edge
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": True, "permit_fee_cents": 12000})
    api.create_payment(
        th.create_payment_payload(ctx["order"]["id"], "DEPOSIT", 0), ctx["customer_headers"]
    )
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["payment_status"] == "UNPAID", order


# ---------------------------------------------------------------------------
# Corner: entities / payment_deposit_signed_amount_positive
# ---------------------------------------------------------------------------
def test_deposit_payment_signed_amount_and_capture(api):
    """PRD §3.4: "Each payment carries a `signed_amount_cents`: a `DEPOSIT` or `BALANCE`
    contributes plus its `amount_cents`, while a `REFUND` contributes minus its `amount_cents`."
    PRD §3.4: "Every payment is captured synchronously, so its `status` is `CAPTURED` at
    creation."

    Design: Corner/entities/payment_deposit_signed_amount_positive
    """
    ctx = th.setup_drafting_order(cemetery_over={"requires_permit": True, "permit_fee_cents": 12000})
    payment = th.validate_success(
        api.create_payment(th.create_payment_payload(ctx["order"]["id"], "DEPOSIT", 33880),
                           ctx["customer_headers"]), 201,
    )
    th.assert_payment(payment)
    assert payment["signed_amount_cents"] == 33880, payment
    assert payment["status"] == "CAPTURED", payment
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["amount_paid_cents"] == 33880, order


# ---------------------------------------------------------------------------
# Corner: validations / balance_payment_insufficient_returns_balance_not_paid
# ---------------------------------------------------------------------------
def test_insufficient_balance_payment_returns_balance_not_paid(api):
    """PRD §3.4: "A `BALANCE` payment advances the axis from `DEPOSIT_PAID` to `PAID_IN_FULL`, but
    only if the cumulative captured `amount_paid_cents` after the payment reaches at least
    `contract_total_cents`; a balance that leaves the paid amount short of the full contract is
    rejected with `ERR_BALANCE_NOT_PAID`."

    Design: Corner/validations/balance_payment_insufficient_returns_balance_not_paid
    """
    ctx = th.setup_deposit_paid_order(
        deposit_cents=33880, cemetery_over={"requires_permit": True, "permit_fee_cents": 12000},
    )
    resp = api.create_payment(
        th.create_payment_payload(ctx["order"]["id"], "BALANCE", 1000), ctx["customer_headers"]
    )
    th.validate_error(resp, th.ApiErrorId.ERR_BALANCE_NOT_PAID.value)
    order = th.validate_success(api.get_order(ctx["order"]["id"], ctx["customer_headers"]))
    assert order["payment_status"] == "DEPOSIT_PAID", order
