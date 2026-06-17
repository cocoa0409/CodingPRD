"""Payments, the order ledger, refunds, and the cancel cash-conservation cascade.

Translates queue A (Difficulty) transitive_cascade (cancel instance) and
compensating_invariant (cash instance), plus queue B (Corner) validations / errors /
cross_cutting reconciliation instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_order, add_line, measure_line, quote, pay,
    setup_quoted_order, setup_deposit_paid_order, setup_ready_order,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ===========================================================================
# Difficulty: transitive_cascade / cancel_triggers_refund_then_amount_paid_then_balance_due
# ===========================================================================
def test_cancel_triggers_refund_amount_paid_and_balance_due(api):
    """PRD §3.8: "If the order's `amount_paid` is greater than zero, the system
    creates an applied refund payment whose `kind` is `REFUND` and whose `amount`
    equals the current `amount_paid`, then recomputes `amount_paid` and `balance_due`
    from the ledger and sets the order's `payment_status` to `REFUNDED`."
    PRD §3.5: "The `balance_due` is that effective total minus `amount_paid`, rounded
    to two decimal places."

    Design: Difficulty/transitive_cascade/cancel_triggers_refund_then_amount_paid_then_balance_due
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                  deposit_amount=25.00)
    cancelled = get_success_data(api.cancel_order(quoted["id"], CLERK))
    assert cancelled["production_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["amount_paid"] == 0.00
    # effective_total is estimate_total 64.47 (no final invoice); balance_due = 64.47 - 0.00
    assert cancelled["balance_due"] == 64.47


def test_cancel_creates_refund_payment_in_ledger(api):
    """PRD §3.8: "the system creates an applied refund payment whose `kind` is
    `REFUND` and whose `amount` equals the current `amount_paid`".
    PRD §3.5: "The order's `amount_paid` is computed by summing the `amount` of every
    applied `DEPOSIT` and `BALANCE` payment, subtracting the `amount` of every applied
    `REFUND` payment, and rounding the difference to two decimal places."

    Second test for the cancel-cascade instance: the refund payment is visible in the
    ledger and zeroes the net cash.

    Design: Difficulty/transitive_cascade/cancel_triggers_refund_then_amount_paid_then_balance_due
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                  deposit_amount=25.00)
    get_success_data(api.cancel_order(quoted["id"], CLERK))
    payments, meta = _list_payments(api, quoted["id"])
    kinds = [p["kind"] for p in payments]
    assert "REFUND" in kinds, f"expected a REFUND payment, got {kinds}"
    refund = next(p for p in payments if p["kind"] == "REFUND")
    assert refund["amount"] == 25.00
    assert refund["payment_status"] == "APPLIED"


# ===========================================================================
# Difficulty: compensating_invariant / cancel_refund_conserves_net_cash_to_zero
# ===========================================================================
def test_cancel_refund_conserves_net_cash_to_zero(api):
    """PRD §3.8: "If the order's `amount_paid` is greater than zero, the system
    creates an applied refund payment whose `kind` is `REFUND` and whose `amount`
    equals the current `amount_paid`, then recomputes `amount_paid` and `balance_due`
    from the ledger and sets the order's `payment_status` to `REFUNDED`."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_cash_to_zero
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                  deposit_amount=25.00)
    cancelled = get_success_data(api.cancel_order(quoted["id"], CLERK))
    assert cancelled["amount_paid"] == 0.00
    assert cancelled["payment_status"] == "REFUNDED"


def test_cancel_refund_conserves_cash_with_larger_deposit(api):
    """PRD §3.8: "the system creates an applied refund payment whose `kind` is
    `REFUND` and whose `amount` equals the current `amount_paid`, then recomputes
    `amount_paid` ... and sets the order's `payment_status` to `REFUNDED`."

    Second test for the cash-conservation invariant: a different (larger) deposit
    amount still nets to exactly 0.00 after the compensating refund.

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_cash_to_zero
    """
    # 16x20 museum line, deposit_pct 0.50 (fragile floor), deposit 200.00 paid.
    cust, quoted, line = setup_deposit_paid_order(
        deposit_pct=0.50, measure_dims=(16, 20), deposit_amount=200.00,
        line_overrides={"glass_type": "MUSEUM", "molding_rate_per_ui": 0.45,
                        "nominal_width_in": 16, "nominal_height_in": 20})
    cancelled = get_success_data(api.cancel_order(quoted["id"], CLERK))
    assert cancelled["amount_paid"] == 0.00
    assert cancelled["payment_status"] == "REFUNDED"


# ===========================================================================
# Corner: validations / errors (fiscal)
# ===========================================================================
def test_deposit_payment_below_required_returns_deposit_too_low(api):
    """PRD §3.5: "the deposit's `amount` must be at least the order's
    `deposit_required`; an amount below the required deposit is rejected with
    `ERR_DEPOSIT_TOO_LOW`."

    Design: Corner/validations/deposit_payment_below_required_returns_deposit_too_low
    """
    cust, quoted, line = setup_quoted_order(deposit_pct=0.30, measure_dims=(8, 10))
    assert quoted["deposit_required"] == 25.00
    resp = api.apply_payment(quoted["id"], {"kind": "DEPOSIT", "amount": 24.00}, CLERK)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_TOO_LOW)


def test_deposit_pct_out_of_range_rejected_on_order_create(api):
    """PRD §3.2: "The `deposit_pct` is the requested deposit fraction of the estimate
    and defaults to 0.30; it must be at least 0.10 and at most 1.00, and a value
    outside that closed range is rejected as an invalid request."

    Design: Corner/validations/deposit_pct_out_of_range_rejected_on_order_create
    """
    cust = create_customer()
    resp = api.create_order({"customer_id": cust["id"], "deposit_pct": 0.05}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_quote_with_only_void_lines_returns_no_lines(api):
    """PRD §3.4: "It is permitted only when the order has at least one frame line that
    is not voided; an order with no such line is rejected with `ERR_NO_LINES`."

    Design: Corner/validations/quote_with_only_void_lines_returns_no_lines
    """
    cust = create_customer()
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="Only",
                    nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    get_success_data(api.void_frame_line(line["id"], DESIGNER))
    resp = api.quote_order(order["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_NO_LINES)


def test_measure_with_nonpositive_dimension_returns_invalid_dimensions(api):
    """PRD §3.2: "the bench technician records `measured_width_in` and
    `measured_height_in` (each strictly greater than zero, in inches — a non-positive
    value is rejected with `ERR_INVALID_DIMENSIONS`)".

    Design: Corner/validations/measure_with_nonpositive_dimension_returns_invalid_dimensions
    """
    cust = create_customer()
    order = create_order(cust["id"])
    line = add_line(order["id"], order["version"], artwork_label="Dm",
                    nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    resp = api.measure_frame_line(line["id"], {"measured_width_in": 0, "measured_height_in": 10}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_DIMENSIONS)


def test_existence_checked_before_state_on_measure_of_missing_line(api):
    """PRD §2.6: "third, existence of every path and body resource id, validated
    left-to-right (the 404 family above) ... sixth, the target resource's state being
    valid for the requested transition".
    PRD §2.5: "`ERR_LINE_NOT_FOUND` for a frame line".

    Design: Corner/validations/existence_checked_before_state_on_measure_of_missing_line
    """
    resp = api.measure_frame_line("00000000-0000-4000-8000-00000000line0",
                                  {"measured_width_in": 8, "measured_height_in": 10}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_FOUND)


def test_balance_payment_insufficient_to_reach_total_rejected(api):
    """PRD §3.5: "The rule is that after applying this payment the order's
    `amount_paid` must reach at least the effective total ... A balance payment that
    does not bring `amount_paid` up to the effective total is rejected with
    `ERR_PAYMENT_INSUFFICIENT`."

    Design: Corner/validations/balance_payment_insufficient_to_reach_total_rejected
    """
    cust, ready, line, bench, task = setup_ready_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                       deposit_amount=25.00)
    assert ready["final_invoice_total"] == 64.47
    # amount_paid would be 35.00 < 64.47
    resp = api.apply_payment(ready["id"], {"kind": "BALANCE", "amount": 10.00}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_INSUFFICIENT)


def test_balance_outstanding_on_pickup_of_ready_unpaid_order(api):
    """PRD §3.7: "Pickup is permitted only when the order's `payment_status` is
    `PAID_IN_FULL`; an order with any outstanding balance is rejected with
    `ERR_BALANCE_OUTSTANDING`."

    Design: Corner/errors/balance_outstanding_on_pickup_of_ready_unpaid_order
    """
    cust, ready, line, bench, task = setup_ready_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                       deposit_amount=25.00)
    # READY but only the deposit applied (DEPOSIT_PAID): state check passes, fiscal fails.
    resp = api.pickup_order(ready["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING)


# ===========================================================================
# Corner: cross_cutting_complexity_layers (reconciliation / cascade)
# ===========================================================================
def test_derived_balance_due_reconciled_after_deposit(api):
    """PRD §3.5: "A successful deposit recomputes `amount_paid` and `balance_due`".
    PRD §3.5: "The `balance_due` is that effective total minus `amount_paid`, rounded
    to two decimal places."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_due_reconciled_after_deposit
    """
    cust, quoted, line = setup_quoted_order(deposit_pct=0.30, measure_dims=(8, 10))
    assert quoted["estimate_total"] == 64.47
    pay(quoted["id"], "DEPOSIT", 25.00)
    refreshed = get_success_data(api.get_order(quoted["id"], CLERK))
    assert refreshed["amount_paid"] == 25.00
    assert refreshed["balance_due"] == 39.47


def test_balance_paid_before_ready_covers_estimate_reaches_paid_in_full(api):
    """PRD §3.5: "A **balance** payment advances `payment_status` to `PAID_IN_FULL`".
    PRD §3.5: "This means a balance may be paid before the order is marked ready only
    if it covers the estimate total".

    Design: Corner/cross_cutting_complexity_layers/balance_paid_before_ready_covers_estimate_reaches_paid_in_full
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10),
                                                  deposit_amount=25.00)
    pay(quoted["id"], "BALANCE", 39.47)
    refreshed = get_success_data(api.get_order(quoted["id"], CLERK))
    assert refreshed["payment_status"] == "PAID_IN_FULL"
    assert refreshed["balance_due"] == 0.00


# ---------------------------------------------------------------------------
def _list_payments(api, order_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_payments(order_id, CLERK))
